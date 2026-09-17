"""
Universal Brain - Dependency Coordinator & Deadlock Detection

Implements M7 Sections 59-63:
- Coordinates complex multi-agent task and external dependencies;
- Runs cycle detection algorithms to detect DEPENDENCY_DEADLOCK;
- Detects circular resource contention (hold-and-wait deadlock).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from universal_brain.autonomy.errors import DependencyDeadlockError, ResourceDeadlockError


class DependencyCoordinator:
    """Detects graph deadlocks and manages mission dependency readiness."""

    def __init__(self) -> None:
        # Adjacency list: node_id -> list of node_ids it depends on
        self._graph: Dict[str, Set[str]] = {}
        # Resource allocation: agent_id -> list of resources held
        self._held_resources: Dict[str, Set[str]] = {}
        # Resource wait: agent_id -> resource waiting on
        self._waiting_resources: Dict[str, str] = {}

    def add_dependency(self, blocked_node: str, required_node: str) -> None:
        """Records that blocked_node depends on required_node."""
        if blocked_node not in self._graph:
            self._graph[blocked_node] = set()
        self._graph[blocked_node].add(required_node)
        self.check_for_deadlocks()

    def remove_dependency(self, blocked_node: str, required_node: str) -> None:
        """Removes a satisfied dependency."""
        if blocked_node in self._graph:
            self._graph[blocked_node].discard(required_node)

    def check_for_deadlocks(self) -> None:
        """
        Executes cycle detection across all registered dependency edges.
        Raises DependencyDeadlockError with cycle details if a circular wait is discovered (M7 Section 61).
        """
        visited: Set[str] = set()
        rec_stack: Set[str] = set()
        path: List[str] = []

        def dfs(node: str) -> Optional[List[str]]:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in self._graph.get(node, set()):
                if neighbor not in visited:
                    res = dfs(neighbor)
                    if res:
                        return res
                elif neighbor in rec_stack:
                    # Cycle found!
                    idx = path.index(neighbor)
                    return path[idx:] + [neighbor]

            path.pop()
            rec_stack.remove(node)
            return None

        for n in list(self._graph.keys()):
            if n not in visited:
                cycle = dfs(n)
                if cycle:
                    cycle_str = " -> ".join(cycle)
                    raise DependencyDeadlockError(
                        f"DEPENDENCY_DEADLOCK detected in task graph: {cycle_str}"
                    )

    def register_resource_hold(self, agent_id: str, resource_id: str) -> None:
        if agent_id not in self._held_resources:
            self._held_resources[agent_id] = set()
        self._held_resources[agent_id].add(resource_id)

    def register_resource_wait(self, agent_id: str, resource_id: str) -> None:
        self._waiting_resources[agent_id] = resource_id
        # Check hold-and-wait cycle
        # Who holds resource_id?
        holder = None
        for a, res_set in self._held_resources.items():
            if resource_id in res_set:
                holder = a
                break

        if holder:
            # Does holder wait for something held by agent_id?
            holder_waits_for = self._waiting_resources.get(holder)
            if holder_waits_for and holder_waits_for in self._held_resources.get(agent_id, set()):
                raise ResourceDeadlockError(
                    f"RESOURCE_DEADLOCK detected: {agent_id} holds '{holder_waits_for}' waiting for '{resource_id}' held by {holder}."
                )

    def release_resource(self, agent_id: str, resource_id: str) -> None:
        if agent_id in self._held_resources:
            self._held_resources[agent_id].discard(resource_id)
        if self._waiting_resources.get(agent_id) == resource_id:
            self._waiting_resources.pop(agent_id, None)

    def clear(self) -> None:
        self._graph.clear()
        self._held_resources.clear()
        self._waiting_resources.clear()
