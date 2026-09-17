"""
Universal Brain - FastAPI Application Factory

Configures CORS, mounts REST routers, WebSocket streaming endpoints,
and initializes baseline singleton domain state.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator
from uuid import UUID

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from universal_brain.api.actions import ActionStatus
from universal_brain.api.dependencies import get_container
from universal_brain.api.router import router as api_v1_router
from universal_brain.config import settings
from universal_brain.kernel.events import ActionClass, EventType


def preseed_baseline_domain_state() -> None:
    """Pre-seeds realistic domain state into the runtime singletons."""
    container = get_container()

    # 1. Preseed Event Chain in EventStore if empty
    if container.event_store.event_count == 0:
        p_id = UUID("00000000-0000-0000-0000-000000000001")
        t_id = UUID("00000000-0000-0000-0000-000000000002")

        e1 = container.event_store.append_event(
            event_type=EventType.USER_INPUT,
            actor_id="operator",
            payload={"utterance": "Design and deploy a verified ROS 2 Humble PID controller for humanoid balance."},
            project_id=p_id,
        )

        e2 = container.event_store.append_event(
            event_type=EventType.INTENT_PARSED,
            actor_id="executive_kernel",
            payload={
                "goal": "Humanoid PID Controller Bringup",
                "requirements": ["REQ-001", "REQ-002"],
                "action_ceiling": "A2",
            },
            project_id=p_id,
            caused_by_event_id=e1.event_id,
        )

        e3 = container.event_store.append_event(
            event_type=EventType.CONTRACT_CREATED,
            actor_id="alignment_engine",
            payload={"contract_id": "00000000-0000-0000-0000-000000000010", "version": 1, "status": "active"},
            project_id=p_id,
            caused_by_event_id=e2.event_id,
        )

        e4 = container.event_store.append_event(
            event_type=EventType.TASK_ASSIGNED,
            actor_id="executive_router",
            payload={"task_id": str(t_id), "assigned_agent": "RoboticsCoder", "model": "claude-3-5-sonnet"},
            project_id=p_id,
            task_id=t_id,
            caused_by_event_id=e3.event_id,
        )

        e5 = container.event_store.append_event(
            event_type=EventType.TOOL_CALLED,
            actor_id="RoboticsCoder",
            payload={"tool": "patch_file", "target": "./src/pid_controller.cpp", "lines_changed": 48},
            project_id=p_id,
            task_id=t_id,
            caused_by_event_id=e4.event_id,
        )

        container.event_store.append_event(
            event_type=EventType.EVIDENCE_PRODUCED,
            actor_id="tool_gateway",
            payload={
                "evidence_type": "colcon_build_log",
                "summary": "14/14 unit tests passed. Headless Gazebo physics simulation completed with 0 collisions.",
                "build_exit_code": 0,
            },
            project_id=p_id,
            task_id=t_id,
            caused_by_event_id=e5.event_id,
        )

    # 2. Preseed a pending A2 consequential proposal if none exist
    if not container.action_manager.list_proposals():
        container.action_manager.create_proposal(
            project_id=UUID("00000000-0000-0000-0000-000000000001"),
            task_id=UUID("00000000-0000-0000-0000-000000000002"),
            contract_id=UUID("00000000-0000-0000-0000-000000000010"),
            contract_version=1,
            action_type="PHYSICAL_TESTBED_DEPLOYMENT",
            target_resource="/dev/ttyUSB0 (CAN Bus Transceiver - Humanoid Actuators)",
            action_class=ActionClass.A2,
            requested_effect="Enable CAN bus power relay and stream trajectory target to knee pitch motors.",
            payload={"launch_file": "humanoid_bringup.launch.py", "baud_rate": 1000000, "can_channel": "can0"},
            required_capabilities=["can:transmit", "relay:power_on"],
            diff_preview="+ CAN_TRANSCEIVER_ENABLE = 0x01;\n+ ros2 launch humanoid_bringup physical.launch.py",
            rollback_plan="Immediate SIGINT on launch process, followed by GPIO relay power disconnect to CAN bus.",
            preflight_passed=True,
            evidence_items_count=3,
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle."""
    preseed_baseline_domain_state()
    yield


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(
        title="Universal Brain Sovereign Control Plane API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS configuration for local-first console
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount REST routes
    app.include_router(api_v1_router)

    # WebSocket Realtime Endpoint
    @app.websocket("/ws/stream")
    async def websocket_stream(websocket: WebSocket) -> None:
        container = get_container()
        await container.ws_gateway.connect(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                    action = msg.get("action")
                    if action == "subscribe":
                        last_seq = msg.get("last_confirmed_sequence", 0)
                        replay = container.ws_gateway.get_replay_events(last_seq)
                        if replay is None:
                            await websocket.send_text(json.dumps({"type": "SNAPSHOT_REQUIRED"}))
                        else:
                            for envelope in replay:
                                await websocket.send_text(envelope.model_dump_json())
                    elif action == "ping":
                        await websocket.send_text(json.dumps({"type": "PONG", "timestamp": datetime.now(timezone.utc).isoformat()}))
                except Exception:
                    pass
        except WebSocketDisconnect:
            await container.ws_gateway.disconnect(websocket)

    return app


app = create_app()
