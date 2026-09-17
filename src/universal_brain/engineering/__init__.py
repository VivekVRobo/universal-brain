"""Universal Brain V5 Autonomous Engineering Agency Runtime.

Implements REQ-ENG-001..REQ-ENG-033 while preserving ALN-001, ALN-009,
ALN-010, ALN-014, ALN-016, ALN-020 and REQ-TOL-001.
"""

from .schemas import (
    EngineeringWorkspace,
    EngineeringToolObservation,
    EngineeringNodeRun,
    EngineeringDAGRun,
    VerificationCommand,
    VerificationCheckResult,
)
from .planning import HierarchicalEngineeringPlanner, TaskDAGMutator, PlanMutationError
from .verification import (
    ExecutableVerificationAdapter,
    VerificationPolicy,
    ImpactAwareVerificationSelector,
    ImpactAwareExecutableVerificationAdapter,
)
from .agency import EngineeringAgencyRuntime, EngineeringToolExecutor, ToolGatewayProposalExecutor
from .code_graph import CodeGraphIndex, CodeGraphIndexer, CodeGraphDelta, SymbolRecord, SymbolKind
from .git_engine import GitTransactionEngine, GitTransactionError
from .local_resources import (
    LocalModelResourceProfile,
    LocalResourceSnapshot,
    OllamaResourceManager,
    OllamaRouteResourcePolicy,
)
from .completion import ProjectCompletionAuditor, ProjectCompletionReport
from .worker_verification import VerifiedWorkerCompletionGate, WorkerCompletionDecision
from .context_source import CodeGraphContextSource
from .replanning import AdaptiveEngineeringReplanner, DeterministicFailureClassifier, FailureKind
from .workspace_inspector import EngineeringWorkspaceInspector

from .checkpointing import (
    EngineeringMissionCheckpoint,
    EngineeringCheckpointStore,
    EngineeringCheckpointError,
    WorkspaceFingerprint,
    WorkspaceFingerprinter,
)
from .audit import EngineeringCausalAuditor
from .worktrees import (
    RequirementWorktreeBinding,
    RequirementWorktreeManager,
    WorktreeCapacityError,
    WorkspaceScopedToolExecutor,
)
from .dependency import DependencyFailureDiagnoser, DependencyRepairPlan, DependencyEcosystem
from .services import PersistentServiceSupervisor, ServiceRecord, ServiceState
from .factory import EngineeringAgencyStack, build_engineering_agency_stack


from .semantic import (
    DiagnosticSeverity,
    DiagnosticDocumentState,
    IncrementalDiagnosticRegistry,
    LspRenamePlanner,
    LspSemanticProvider,
    RefactorTextEdit,
    SemanticBackendUnavailable,
    SemanticDiagnostic,
    SemanticGraphSnapshot,
    SemanticLocation,
    SemanticReferenceFact,
    SemanticSymbolFact,
    SourcePosition,
    SourceRange,
    SymbolRenamePlan,
    TreeSitterSemanticProvider,
)
from .isolation import (
    AuthorityGatedIsolationRuntime,
    HyperVIsolationProvider,
    IsolationCapabilities,
    IsolationCommandPlan,
    IsolationError,
    IsolationQuota,
    NetworkMode,
    WSL2IsolationProvider,
)
from .distributed_leases import DurableLeaseError, DurableWorkerLease, DurableWorkerLeaseStore
from .multirepo import (
    MultiRepositoryGraph,
    MultiRepositoryGraphBuilder,
    RepositoryDependencyEdge,
    RepositoryDescriptor,
)
from .merge_coordinator import (
    ExecutableMergedTreeVerifier,
    MergeIntegrationResult,
    MergeVerificationDecision,
    SerializedMergeCoordinator,
)
from .remediation import DependencyRemediationCoordinator, DependencyRemediationResult
from .endurance import EnduranceCycleResult, EnduranceRunReport, EngineeringEnduranceHarness
from .observability import EngineeringStatusSnapshot, build_engineering_observability_snapshot
from .services import ToolGatewayServiceBackend

from .lsp_runtime import LspProtocolError, StdioLspBackend
from .isolation_tool import IsolationPlanExecutionTool, ToolGatewayIsolationBackend
from .evidence import (
    EvidenceStatus,
    TargetEvidenceItem,
    TargetMachineEvidenceReport,
    V52TargetEvidenceCollector,
)

from .validation import (
    ValidationError,
    V53ScenarioResult,
    V53ValidationCheckpoint,
    V53ValidationCheckpointStore,
    V53EvidenceArtifact,
    V53EvidenceManifest,
    V53EvidenceBundler,
    HttpOllamaProbeClient,
    V53OllamaValidator,
    V53DisposableGitLab,
    V53ValidationReport,
    V53RealEnvironmentValidator,
    V53AuthorityServiceScenario,
    V53OllamaPressureScenario,
    V53RestartRecoveryLab,
    V53WSLIsolationExecutionScenario,
)

__all__ = [
    "EngineeringWorkspace",
    "EngineeringToolObservation",
    "EngineeringNodeRun",
    "EngineeringDAGRun",
    "VerificationCommand",
    "VerificationCheckResult",
    "HierarchicalEngineeringPlanner",
    "TaskDAGMutator",
    "PlanMutationError",
    "ExecutableVerificationAdapter",
    "VerificationPolicy",
    "EngineeringAgencyRuntime",
    "EngineeringToolExecutor",
    "ToolGatewayProposalExecutor",
    "CodeGraphIndex",
    "CodeGraphIndexer",
    "SymbolRecord",
    "SymbolKind",
    "GitTransactionEngine",
    "GitTransactionError",
    "LocalModelResourceProfile",
    "LocalResourceSnapshot",
    "OllamaResourceManager",
    "ProjectCompletionAuditor",
    "ProjectCompletionReport",
    "VerifiedWorkerCompletionGate",
    "WorkerCompletionDecision",
    "CodeGraphContextSource",
    "AdaptiveEngineeringReplanner",
    "DeterministicFailureClassifier",
    "FailureKind",
    "EngineeringWorkspaceInspector",
    "ImpactAwareVerificationSelector",
    "ImpactAwareExecutableVerificationAdapter",
    "CodeGraphDelta",
    "OllamaRouteResourcePolicy",
    "EngineeringMissionCheckpoint",
    "EngineeringCheckpointStore",
    "EngineeringCheckpointError",
    "WorkspaceFingerprint",
    "WorkspaceFingerprinter",
    "EngineeringCausalAuditor",
    "RequirementWorktreeBinding",
    "RequirementWorktreeManager",
    "WorktreeCapacityError",
    "WorkspaceScopedToolExecutor",
    "DependencyFailureDiagnoser",
    "DependencyRepairPlan",
    "DependencyEcosystem",
    "PersistentServiceSupervisor",
    "ServiceRecord",
    "ServiceState",
    "EngineeringAgencyStack",
    "build_engineering_agency_stack",
    "DiagnosticSeverity",
    "DiagnosticDocumentState",
    "IncrementalDiagnosticRegistry",
    "LspRenamePlanner",
    "LspSemanticProvider",
    "RefactorTextEdit",
    "SemanticBackendUnavailable",
    "SemanticDiagnostic",
    "SemanticGraphSnapshot",
    "SemanticLocation",
    "SemanticReferenceFact",
    "SemanticSymbolFact",
    "SourcePosition",
    "SourceRange",
    "SymbolRenamePlan",
    "TreeSitterSemanticProvider",
    "AuthorityGatedIsolationRuntime",
    "HyperVIsolationProvider",
    "IsolationCapabilities",
    "IsolationCommandPlan",
    "IsolationError",
    "IsolationQuota",
    "NetworkMode",
    "WSL2IsolationProvider",
    "DurableLeaseError",
    "DurableWorkerLease",
    "DurableWorkerLeaseStore",
    "MultiRepositoryGraph",
    "MultiRepositoryGraphBuilder",
    "RepositoryDependencyEdge",
    "RepositoryDescriptor",
    "ExecutableMergedTreeVerifier",
    "MergeIntegrationResult",
    "MergeVerificationDecision",
    "SerializedMergeCoordinator",
    "DependencyRemediationCoordinator",
    "DependencyRemediationResult",
    "EnduranceCycleResult",
    "EnduranceRunReport",
    "EngineeringEnduranceHarness",
    "EngineeringStatusSnapshot",
    "build_engineering_observability_snapshot",
    "ToolGatewayServiceBackend",

    "LspProtocolError",
    "StdioLspBackend",
    "IsolationPlanExecutionTool",
    "ToolGatewayIsolationBackend",
    "EvidenceStatus",
    "TargetEvidenceItem",
    "TargetMachineEvidenceReport",
    "V52TargetEvidenceCollector",
    "ValidationError",
    "V53ScenarioResult",
    "V53ValidationCheckpoint",
    "V53ValidationCheckpointStore",
    "V53EvidenceArtifact",
    "V53EvidenceManifest",
    "V53EvidenceBundler",
    "HttpOllamaProbeClient",
    "V53OllamaValidator",
    "V53DisposableGitLab",
    "V53ValidationReport",
    "V53RealEnvironmentValidator",
    "V53AuthorityServiceScenario",
    "V53OllamaPressureScenario",
    "V53RestartRecoveryLab",
    "V53WSLIsolationExecutionScenario",
]
