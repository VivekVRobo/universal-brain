from .base import BaseModelTransport,TransportOutageError,TransportRateLimitError
from ..schemas import *
class MockTransport(BaseModelTransport):
    def __init__(self): self.fail_routes=set();self.rate_limit_routes=set();self.outputs={}
    def supports(self,route): return True
    async def invoke(self,model,route,request):
        if route.route_id in self.rate_limit_routes: raise TransportRateLimitError('mock rate limit',60)
        if route.route_id in self.fail_routes: raise TransportOutageError('mock outage')
        text=self.outputs.get(route.route_id,'ok')
        return NormalizedModelResult(request_id=request.request_id,model_key=model.model_key,route_id=route.route_id,output_text=text,usage=ModelUsage(input_tokens=100,output_tokens=50),conversation_ref=f'mock://{route.route_id}/{request.request_id}')
