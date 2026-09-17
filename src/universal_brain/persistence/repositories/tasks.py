"""
Universal Brain - Task & DAG Repositories

Implements M6 Sections 13, 29-32:
Persists declarative Task DAGs, nodes, and dependencies with strict optimistic concurrency control.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from universal_brain.executive.schemas import TaskNode
from universal_brain.persistence.errors import OptimisticConcurrencyError
from universal_brain.persistence.models import TaskDependencyORM, TaskORM
from universal_brain.persistence.repositories.base import BaseRepository


class TaskRepository(BaseRepository[TaskORM]):
    """Manages task lifecycle with optimistic concurrency verification."""

    async def save_task(
        self,
        task_node: TaskNode,
        project_id: UUID,
        task_id: Optional[UUID] = None,
    ) -> TaskORM:
        """Persists or registers a task node."""
        try:
            tid = task_id or uuid4()
            orm_task = TaskORM(
                task_id=tid,
                project_id=project_id,
                dag_id=task_node.dag_id,
                node_id=task_node.node_id,
                goal=task_node.goal,
                description=task_node.description,
                action_class=task_node.action_class.value if hasattr(task_node.action_class, "value") else str(task_node.action_class),
                status=task_node.status.value if hasattr(task_node.status, "value") else str(task_node.status),
                version=task_node.version,
                task_data=task_node.model_dump(mode="json"),
            )
            self.session.add(orm_task)
            await self.session.flush()
            return orm_task
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_task(self, task_id: UUID) -> Optional[TaskORM]:
        stmt = select(TaskORM).where(TaskORM.task_id == task_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_tasks_for_dag(self, dag_id: UUID) -> List[TaskORM]:
        stmt = select(TaskORM).where(TaskORM.dag_id == dag_id)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def update_task_status_with_version(
        self,
        task_id: UUID,
        expected_version: int,
        new_status: str,
        updated_data: Optional[Dict[str, Any]] = None,
    ) -> TaskORM:
        """
        Updates task status under strict optimistic locking (M6 Section 13).
        Raises OptimisticConcurrencyError if expected_version != current version.
        """
        try:
            now = datetime.now(timezone.utc)
            values: Dict[str, Any] = {
                "status": new_status,
                "version": TaskORM.version + 1,
                "updated_at": now,
            }
            if updated_data is not None:
                values["task_data"] = updated_data

            stmt = (
                update(TaskORM)
                .where(TaskORM.task_id == task_id, TaskORM.version == expected_version)
                .values(**values)
                .returning(TaskORM)
            )

            res = await self.session.execute(stmt)
            updated_task = res.scalar_one_or_none()
            if not updated_task:
                raise OptimisticConcurrencyError(
                    f"Task '{task_id}' concurrency conflict: expected version {expected_version}, "
                    f"but record was modified or does not exist."
                )

            await self.session.flush()
            return updated_task
        except Exception as e:
            raise self._translate_exception(e) from e

    async def save_dependencies(self, dag_id: UUID, dependencies: List[Tuple[str, str]]) -> None:
        """Saves edges between task node IDs."""
        try:
            for task_node_id, depends_on_node_id in dependencies:
                dep = TaskDependencyORM(
                    dag_id=dag_id,
                    task_node_id=task_node_id,
                    depends_on_node_id=depends_on_node_id,
                )
                self.session.add(dep)
            await self.session.flush()
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_dependencies(self, dag_id: UUID) -> List[TaskDependencyORM]:
        stmt = select(TaskDependencyORM).where(TaskDependencyORM.dag_id == dag_id)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
