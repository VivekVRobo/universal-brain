from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from typing import Optional
from .schemas import RouteHealth
@dataclass
class RouteHealthRecord: state:RouteHealth=RouteHealth.HEALTHY; consecutive_failures:int=0; opened_at:Optional[datetime]=None; last_error:Optional[str]=None
class RouteHealthRegistry:
    def __init__(self,failure_threshold=3,reset_timeout_seconds=60): self.failure_threshold=failure_threshold; self.reset_timeout=timedelta(seconds=reset_timeout_seconds); self._records={}
    def _r(self,k): return self._records.setdefault(k,RouteHealthRecord())
    def get_state(self,k,now=None):
        r=self._r(k); now=now or datetime.now(timezone.utc)
        if r.state==RouteHealth.OPEN and r.opened_at and now-r.opened_at>=self.reset_timeout:r.state=RouteHealth.DEGRADED
        return r.state
    def record_success(self,k): self._records[k]=RouteHealthRecord()
    def record_failure(self,k,error=''):
        r=self._r(k); r.consecutive_failures+=1; r.last_error=error or r.last_error
        if r.consecutive_failures>=self.failure_threshold:r.state=RouteHealth.OPEN;r.opened_at=datetime.now(timezone.utc)
        else:r.state=RouteHealth.DEGRADED
    def mark_auth_required(self,k,error='Authentication required'): r=self._r(k);r.state=RouteHealth.AUTH_REQUIRED;r.last_error=error
    def disable(self,k,reason='Disabled'): r=self._r(k);r.state=RouteHealth.DISABLED;r.last_error=reason
    def enable(self,k): self._records[k]=RouteHealthRecord()
