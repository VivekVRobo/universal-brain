from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

from universal_brain.kernel.events import ActionClass


class TransportKind(str, Enum):
    API = "api"
    BROWSER = "browser"
    DESKTOP_APP = "desktop_app"
    LOCAL = "local"


class AuthMode(str, Enum):
    NONE = "none"
    API_KEY = "api_key"
    OAUTH = "oauth"
    USER_SESSION = "user_session"


class RetentionPolicy(str, Enum):
    LOCAL_ONLY = "local_only"
    ZERO_DATA_RETENTION = "zero_data_retention"
    PROVIDER_DEFAULT = "provider_default"
    UNKNOWN = "unknown"


class SensitivityLevel(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    SECRET = "secret"

    @property
    def rank(self) -> int:
        return {
            self.PUBLIC: 0,
            self.INTERNAL: 1,
            self.CONFIDENTIAL: 2,
            self.SECRET: 3,
        }[self]


class ModelCapability(str, Enum):
    REASONING = "reasoning"
    CODING = "coding"
    ARCHITECTURE = "architecture"
    RESEARCH = "research"
    VISION = "vision"
    TOOL_USE = "tool_use"
    COMPUTER_USE = "computer_use"
    LONG_CONTEXT = "long_context"
    STRUCTURED_OUTPUT = "structured_output"
    VERIFICATION = "verification"
    WRITING = "writing"
    SPEED = "speed"


class RouteHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OPEN = "open"
    DISABLED = "disabled"
    AUTH_REQUIRED = "auth_required"


class TaskComplexity(str, Enum):
    TRIVIAL = "trivial"
    STANDARD = "standard"
    COMPLEX = "complex"
    FRONTIER = "frontier"


class StreamEventType(str, Enum):
    STARTED = "started"
    TEXT_DELTA = "text_delta"
    TOOL_CALL = "tool_call"
    USAGE = "usage"
    COMPLETED = "completed"
    ERROR = "error"


class CapabilityProfile(BaseModel):
    scores: Dict[ModelCapability, float] = Field(default_factory=dict)

    @field_validator("scores")
    @classmethod
    def validate_scores(cls, value: Dict[ModelCapability, float]) -> Dict[ModelCapability, float]:
        if any(not 0 <= score <= 1 for score in value.values()):
            raise ValueError("capability scores must be 0..1")
        return value

    def get(self, capability: ModelCapability, default: float = 0.0) -> float:
        return float(self.scores.get(capability, default))


class ModelDescriptor(BaseModel):
    model_key: str = Field(min_length=3)
    vendor: str
    model_id: str
    display_name: str
    family: str
    capability_profile: CapabilityProfile = Field(default_factory=CapabilityProfile)
    context_window: int = Field(default=128_000, gt=0)
    max_output_tokens: int = Field(default=8_192, gt=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class AccessRoute(BaseModel):
    route_id: str = Field(min_length=3)
    model_key: str
    transport: TransportKind
    auth_mode: AuthMode = AuthMode.NONE
    retention_policy: RetentionPolicy = RetentionPolicy.UNKNOWN
    max_sensitivity: SensitivityLevel = SensitivityLevel.INTERNAL
    context_window_override: Optional[int] = Field(default=None, gt=0)
    max_output_tokens_override: Optional[int] = Field(default=None, gt=0)
    cost_per_million_input: float = Field(default=0, ge=0)
    cost_per_million_output: float = Field(default=0, ge=0)
    supports_structured_outputs: bool = True
    supports_tools: bool = True
    supports_vision: bool = False
    latency_class: str = "standard"
    health: RouteHealth = RouteHealth.HEALTHY
    config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    def allows_sensitivity(self, sensitivity: SensitivityLevel) -> bool:
        return sensitivity.rank <= self.max_sensitivity.rank


class TaskProfile(BaseModel):
    task_id: Optional[UUID] = None
    task_kind: str = "general"
    complexity: TaskComplexity = TaskComplexity.STANDARD
    required_context_tokens: int = Field(default=4_000, ge=0)
    estimated_output_tokens: int = Field(default=2_048, ge=0)
    required_capabilities: Set[ModelCapability] = Field(default_factory=set)
    capability_weights: Dict[ModelCapability, float] = Field(default_factory=dict)
    minimum_capability_scores: Dict[ModelCapability, float] = Field(default_factory=dict)
    sensitivity: SensitivityLevel = SensitivityLevel.INTERNAL
    action_class: ActionClass = ActionClass.A0
    require_structured_output: bool = False
    require_tools: bool = False
    require_vision: bool = False
    local_only: bool = False
    allowed_transports: Optional[Set[TransportKind]] = None
    preferred_transports: List[TransportKind] = Field(default_factory=list)
    max_input_cost_per_million: Optional[float] = Field(default=None, ge=0)
    max_output_cost_per_million: Optional[float] = Field(default=None, ge=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CandidateScore(BaseModel):
    model_key: str
    route_id: str
    total_score: float
    capability_score: float
    empirical_score: float = 0.75
    cost_score: float
    privacy_score: float
    health_score: float
    transport_score: float
    context_score: float
    rationale: List[str] = Field(default_factory=list)


class RejectedCandidate(BaseModel):
    model_key: str
    route_id: str
    reason: str


class FabricRoutingDecision(BaseModel):
    decision_id: UUID = Field(default_factory=uuid4)
    model_key: str
    route_id: str
    selected_score: CandidateScore
    alternatives: List[CandidateScore] = Field(default_factory=list)
    rejected: List[RejectedCandidate] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ModelMessage(BaseModel):
    role: str
    content: str


class ModelRequest(BaseModel):
    request_id: UUID = Field(default_factory=uuid4)
    task_id: Optional[UUID] = None
    messages: List[ModelMessage]
    tools: List[Dict[str, Any]] = Field(default_factory=list)
    response_schema: Optional[Dict[str, Any]] = None
    max_output_tokens: Optional[int] = Field(default=None, gt=0)
    temperature: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class NormalizedToolCall(BaseModel):
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    call_id: Optional[str] = None


class ModelUsage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0, ge=0)


class NormalizedModelResult(BaseModel):
    result_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    model_key: str
    route_id: str
    output_text: str = ""
    structured_output: Optional[Dict[str, Any]] = None
    tool_calls: List[NormalizedToolCall] = Field(default_factory=list)
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    usage: ModelUsage = Field(default_factory=ModelUsage)
    provider_request_id: Optional[str] = None
    conversation_ref: Optional[str] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)
    raw_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ModelStreamEvent(BaseModel):
    event_type: StreamEventType
    request_id: UUID
    model_key: str
    route_id: str
    sequence: int = Field(ge=0)
    delta_text: str = ""
    tool_call: Optional[NormalizedToolCall] = None
    usage: Optional[ModelUsage] = None
    final_result: Optional[NormalizedModelResult] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
