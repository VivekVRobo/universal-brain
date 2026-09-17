"""Read-only Engineering Agency observability snapshot for V5.2."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class EngineeringWorktreeStatus(BaseModel):
    requirement_ref: str
    branch: str
    path: str
    node_count: int
    verified_commit: str | None = None
    integrated_commit: str | None = None


class EngineeringLeaseStatus(BaseModel):
    task_id: str
    worker_id: str
    workspace_id: str
    generation: int
    expires_at: str


class EngineeringServiceStatus(BaseModel):
    name: str
    service_id: str
    state: str
    pid: int | None = None
    cwd: str


class EngineeringStatusSnapshot(BaseModel):
    configured: bool = True
    repository_root: str
    symbol_count: int = 0
    reference_count: int = 0
    indexed_files: int = 0
    active_worktrees: list[EngineeringWorktreeStatus] = Field(default_factory=list)
    durable_worker_leases: list[EngineeringLeaseStatus] = Field(default_factory=list)
    repository_count: int = 1
    cross_repo_dependency_edges: int = 0
    services: list[EngineeringServiceStatus] = Field(default_factory=list)
    semantic_backends: list[str] = Field(default_factory=list)
    isolation_provider: str | None = None
    note: str | None = None


def build_engineering_observability_snapshot(stack) -> EngineeringStatusSnapshot:
    graph = stack.code_graph
    worktrees = []
    for raw in stack.worktrees.export_bindings().values():
        worktrees.append(
            EngineeringWorktreeStatus(
                requirement_ref=str(raw["requirement_ref"]),
                branch=str(raw["branch"]),
                path=str(raw["path"]),
                node_count=len(raw.get("node_ids") or []),
                verified_commit=raw.get("verified_commit"),
                integrated_commit=raw.get("integrated_commit"),
            )
        )

    leases = []
    lease_store = getattr(stack, "distributed_leases", None)
    if lease_store is not None:
        for lease in lease_store.list_active():
            leases.append(
                EngineeringLeaseStatus(
                    task_id=lease.task_id,
                    worker_id=lease.worker_id,
                    workspace_id=str(lease.workspace_id),
                    generation=lease.generation,
                    expires_at=lease.expires_at.isoformat(),
                )
            )

    services = []
    supervisor = getattr(stack, "service_supervisor", None)
    if supervisor is not None:
        for record in supervisor.list_records():
            services.append(
                EngineeringServiceStatus(
                    name=record.name,
                    service_id=str(record.service_id),
                    state=record.state,
                    pid=record.pid,
                    cwd=str(record.cwd),
                )
            )

    multirepo = getattr(stack, "multi_repo_graph", None)
    repository_count = len(multirepo.repositories) if multirepo is not None else 1
    dependency_edges = len(multirepo.edges) if multirepo is not None else 0
    semantic_backends = list(getattr(stack, "semantic_backends", []) or [])
    isolation = getattr(stack, "isolation_provider", None)
    provider_name = None
    if isolation is not None:
        provider_name = isolation.__class__.__name__

    return EngineeringStatusSnapshot(
        repository_root=str(Path(graph.repository_root)),
        symbol_count=len(graph.symbols),
        reference_count=len(graph.references),
        indexed_files=len(graph.file_digests),
        active_worktrees=sorted(worktrees, key=lambda item: item.requirement_ref),
        durable_worker_leases=sorted(leases, key=lambda item: item.task_id),
        repository_count=repository_count,
        cross_repo_dependency_edges=dependency_edges,
        services=sorted(services, key=lambda item: item.name),
        semantic_backends=semantic_backends,
        isolation_provider=provider_name,
    )
