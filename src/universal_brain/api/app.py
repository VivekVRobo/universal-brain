"""
Universal Brain - FastAPI Application Factory

Configures CORS, authenticated control-plane boundaries, REST routers,
WebSocket streaming endpoints, and baseline singleton domain state.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from universal_brain.api.auth import (
    authenticate_operator_request,
    authenticate_operator_token,
    websocket_operator_token,
)
from universal_brain.api.dependencies import get_container
from universal_brain.api.router import router as api_v1_router
from universal_brain.config import settings


# Worker execution endpoints carry their own scoped worker bearer tokens. Worker
# registration and all operator/query endpoints remain behind operator auth.
_WORKER_AUTH_EXEMPT_PATHS = {
    "/api/v1/workers/poll",
    "/api/v1/workers/progress",
    "/api/v1/workers/complete",
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Runtime startup is state-neutral.

    Operator/demo fixtures belong in tests or explicit demo commands. Starting
    the control plane must never manufacture projects, evidence, approvals, or
    health claims.
    """
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Universal Brain Sovereign Control Plane API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def operator_auth_boundary(request: Request, call_next):
        path = request.url.path.rstrip("/") or "/"
        if path.startswith("/api/v1") and path not in _WORKER_AUTH_EXEMPT_PATHS:
            try:
                request.state.operator_principal = authenticate_operator_request(request)
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": exc.detail},
                    headers=exc.headers or {},
                )
        return await call_next(request)

    app.include_router(api_v1_router)

    @app.websocket("/ws/stream")
    async def websocket_stream(websocket: WebSocket) -> None:
        try:
            principal = authenticate_operator_token(websocket_operator_token(websocket))
        except HTTPException:
            await websocket.close(code=4401, reason="operator authentication required")
            return

        websocket.state.operator_principal = principal
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
                        await websocket.send_text(
                            json.dumps({"type": "PONG", "timestamp": datetime.now(timezone.utc).isoformat()})
                        )
                except Exception:
                    pass
        except WebSocketDisconnect:
            await container.ws_gateway.disconnect(websocket)

    return app


app = create_app()
