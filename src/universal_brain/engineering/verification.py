"""Executable verification adapters for Universal Brain V5.

Traceability: REQ-ENG-004, REQ-VER-001..004, ALN-010, ALN-014, ALN-020,
REQ-TOL-001. Production command execution is delegated to an authority-gated
executor; this module never shells out by itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, Callable, Any

from universal_brain.executive.schemas import TaskNode
from universal_brain.intelligence.mission_runtime import MissionVerificationDecision
from universal_brain.intelligence.schemas import NormalizedModelResult

from .schemas import VerificationCommand, VerificationCheckResult


class VerificationCommandExecutor(Protocol):
    async def run(self, command: VerificationCommand, *, node: TaskNode) -> VerificationCheckResult: ...


class VerificationPolicy:
    """Detect deterministic project checks from repository metadata.

    Detection is conservative: absence of a known check produces no synthetic pass.
    REQ-VER-003 therefore causes verification to fail closed when no check can run.
    """

    def discover(self, workspace_root: Path) -> list[VerificationCommand]:
        root = workspace_root.resolve()
        checks: list[VerificationCommand] = []

        if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists() or (root / "tests").exists():
            checks.append(
                VerificationCommand(
                    check_id="python_pytest",
                    executable="pytest",
                    arguments=["-q"],
                    cwd=root,
                    timeout_seconds=600,
                )
            )

        package_json = root / "package.json"
        if package_json.exists():
            checks.append(
                VerificationCommand(
                    check_id="typescript_typecheck",
                    executable="npm",
                    arguments=["exec", "tsc", "--", "--noEmit"],
                    cwd=root,
                    timeout_seconds=600,
                )
            )

        if (root / "Cargo.toml").exists():
            checks.append(
                VerificationCommand(
                    check_id="rust_tests",
                    executable="cargo",
                    arguments=["test", "--all-targets"],
                    cwd=root,
                    timeout_seconds=900,
                )
            )

        if (root / "src").exists() and (root / "install").exists() and (root / "log").exists():
            checks.append(
                VerificationCommand(
                    check_id="ros_colcon_tests",
                    executable="colcon",
                    arguments=["test", "--event-handlers", "console_direct+"],
                    cwd=root,
                    timeout_seconds=1200,
                )
            )
        return checks


class ImpactAwareVerificationSelector:
    """Select the narrowest safe deterministic checks for a change set.

    Manifest/build-system changes always trigger full verification. For Python
    source changes, a code graph may narrow pytest to impacted test files. If
    impact cannot be established confidently, the selector fails safe by keeping
    the original full checks.
    """

    FULL_VERIFICATION_FILES = {
        "pyproject.toml", "pytest.ini", "tox.ini", "requirements.txt",
        "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
        "Cargo.toml", "Cargo.lock", "CMakeLists.txt",
    }

    def __init__(self, code_graph=None, changed_files_provider=None):
        self.code_graph = code_graph
        self.changed_files_provider = changed_files_provider
        self.last_changed_files: list[str] = []
        self.last_affected_tests: list[str] = []

    def __call__(self, node: TaskNode, checks: list[VerificationCommand]) -> list[VerificationCommand]:
        if self.changed_files_provider is None:
            return checks
        changed = [str(Path(path).as_posix()) for path in self.changed_files_provider(node)]
        self.last_changed_files = changed
        if not changed:
            return checks
        if any(Path(path).name in self.FULL_VERIFICATION_FILES for path in changed):
            self.last_affected_tests = []
            return checks
        if self.code_graph is None:
            return checks
        tests = list(self.code_graph.affected_tests(changed))
        self.last_affected_tests = tests
        if not tests:
            return checks

        selected: list[VerificationCommand] = []
        for command in checks:
            if command.check_id == "python_pytest":
                selected.append(command.model_copy(update={"arguments": ["-q", *tests]}))
            else:
                selected.append(command)
        return selected


class ExecutableVerificationAdapter:
    """Run real deterministic checks and convert them into mission acceptance evidence."""

    def __init__(
        self,
        workspace_root: Path,
        executor: VerificationCommandExecutor,
        *,
        policy: VerificationPolicy | None = None,
        command_selector: Callable[[TaskNode, list[VerificationCommand]], list[VerificationCommand]] | None = None,
        workspace_resolver: Callable[[TaskNode], Path] | None = None,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.executor = executor
        self.policy = policy or VerificationPolicy()
        self.command_selector = command_selector
        self.workspace_resolver = workspace_resolver
        self.last_results: list[VerificationCheckResult] = []
        self.last_workspace_root: Path = self.workspace_root

    async def verify(self, node: TaskNode, result: NormalizedModelResult) -> MissionVerificationDecision:
        active_root = (self.workspace_resolver(node) if self.workspace_resolver else self.workspace_root).resolve()
        self.last_workspace_root = active_root
        checks = self.policy.discover(active_root)
        if self.command_selector:
            checks = self.command_selector(node, checks)
        if not checks:
            self.last_results = []
            return MissionVerificationDecision(
                accepted=False,
                reason="REQ-VER-003/ALN-020: no executable verification check was available",
            )

        results: list[VerificationCheckResult] = []
        for command in checks:
            check = await self.executor.run(command, node=node)
            results.append(check)
            if command.required and not check.passed:
                self.last_results = results
                return MissionVerificationDecision(
                    accepted=False,
                    evidence_refs=[r.evidence_ref for r in results if r.evidence_ref],
                    reason=f"Required verification check failed: {command.check_id}: {check.reason}",
                )

        self.last_results = results
        return MissionVerificationDecision(
            accepted=True,
            evidence_refs=[r.evidence_ref for r in results if r.evidence_ref],
            reason="All required executable verification checks passed",
        )


class ToolGatewayVerificationExecutor:
    """Execute verification commands through the centralized ToolGateway (REQ-TOL-001)."""

    def __init__(self, gateway, contract, capability_token_provider: Callable[[TaskNode, VerificationCommand], Any]):
        self.gateway = gateway
        self.contract = contract
        self.capability_token_provider = capability_token_provider

    async def run(self, command: VerificationCommand, *, node: TaskNode) -> VerificationCheckResult:
        token = self.capability_token_provider(node, command)
        args = {
            "executable": command.executable,
            "arguments": command.arguments,
            "cwd": str(command.cwd),
            "timeout_seconds": command.timeout_seconds,
        }
        try:
            result = self.gateway.execute_tool(
                tool_name="run_command",
                args=args,
                capability_token=token,
                contract=self.contract,
                actor_id="verification_engine",
                target_resource=str(command.cwd),
            )
        except Exception as exc:
            return VerificationCheckResult(
                check_id=command.check_id,
                passed=False,
                reason=f"ToolGateway verification execution failed: {type(exc).__name__}: {exc}",
            )

        evidence = result.evidence or {}
        command_id = evidence.get("command_id") or "unknown"
        return VerificationCheckResult(
            check_id=command.check_id,
            passed=bool(result.success and evidence.get("exit_code") == 0),
            evidence_ref=f"tool://run_command/{command_id}",
            exit_code=evidence.get("exit_code"),
            stdout_digest=evidence.get("stdout_sha256"),
            stderr_digest=evidence.get("stderr_sha256"),
            reason="exit code 0" if result.success else str(result.output)[-1000:],
        )


class ImpactAwareExecutableVerificationAdapter(ExecutableVerificationAdapter):
    """Executable verifier with asynchronous change-impact discovery.

    The changed-files provider is typically GitTransactionEngine.changed_files.
    Full checks remain the fallback whenever impact analysis is uncertain.
    """

    def __init__(
        self,
        workspace_root: Path,
        executor: VerificationCommandExecutor,
        *,
        code_graph=None,
        changed_files_provider=None,
        policy: VerificationPolicy | None = None,
        workspace_resolver: Callable[[TaskNode], Path] | None = None,
    ) -> None:
        super().__init__(
            workspace_root,
            executor,
            policy=policy,
            workspace_resolver=workspace_resolver,
        )
        self.code_graph = code_graph
        self.changed_files_provider = changed_files_provider
        self.last_changed_files: list[str] = []
        self.last_affected_tests: list[str] = []

    async def verify(self, node: TaskNode, result: NormalizedModelResult) -> MissionVerificationDecision:
        active_root = (self.workspace_resolver(node) if self.workspace_resolver else self.workspace_root).resolve()
        self.last_workspace_root = active_root
        checks = self.policy.discover(active_root)
        if not checks:
            self.last_results = []
            return MissionVerificationDecision(
                accepted=False,
                reason="REQ-VER-003/ALN-020: no executable verification check was available",
            )

        changed: list[str] = []
        if self.changed_files_provider is not None:
            maybe = self.changed_files_provider(node)
            changed = await maybe if hasattr(maybe, "__await__") else list(maybe)
        self.last_changed_files = [Path(path).as_posix() for path in changed]
        selector = ImpactAwareVerificationSelector(
            code_graph=self.code_graph,
            changed_files_provider=lambda _node: self.last_changed_files,
        )
        checks = selector(node, checks)
        self.last_affected_tests = selector.last_affected_tests

        results: list[VerificationCheckResult] = []
        for command in checks:
            check = await self.executor.run(command, node=node)
            results.append(check)
            if command.required and not check.passed:
                self.last_results = results
                return MissionVerificationDecision(
                    accepted=False,
                    evidence_refs=[r.evidence_ref for r in results if r.evidence_ref],
                    reason=f"Required verification check failed: {command.check_id}: {check.reason}",
                )
        self.last_results = results
        return MissionVerificationDecision(
            accepted=True,
            evidence_refs=[r.evidence_ref for r in results if r.evidence_ref],
            reason=(
                f"All required executable verification checks passed; impacted_tests={self.last_affected_tests}"
                if self.last_affected_tests
                else "All required executable verification checks passed"
            ),
        )
