"""Authentication boundary for the Universal Brain operator control plane.

Version 1 is single-operator. The caller proves possession of the configured
operator bearer credential; the canonical operator identity is derived entirely
server-side and is never trusted from request JSON.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request, WebSocket, status

from universal_brain.config import settings


@dataclass(frozen=True, slots=True)
class OperatorPrincipal:
    operator_id: str
    auth_method: str = "bearer"


def authenticate_operator_token(token: Optional[str]) -> OperatorPrincipal:
    """Validate the configured single-operator bearer credential fail-closed."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing operator bearer credential.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not hmac.compare_digest(token, settings.operator_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid operator bearer credential.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return OperatorPrincipal(operator_id=settings.operator_id)


def _bearer_from_header(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    scheme, separator, credentials = value.partition(" ")
    if not separator or scheme.lower() != "bearer" or not credentials.strip():
        return None
    return credentials.strip()


def authenticate_operator_request(request: Request) -> OperatorPrincipal:
    return authenticate_operator_token(_bearer_from_header(request.headers.get("Authorization")))


def operator_principal(request: Request) -> OperatorPrincipal:
    """Read the principal attached by the control-plane authentication middleware."""
    principal = getattr(request.state, "operator_principal", None)
    if not isinstance(principal, OperatorPrincipal):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated operator context is unavailable.",
        )
    return principal


def websocket_operator_token(websocket: WebSocket) -> Optional[str]:
    """Extract WebSocket bearer authentication.

    Non-browser clients may use Authorization. Browser clients can use the
    explicit ``access_token`` query parameter until a cookie/session login layer
    is introduced; the server never accepts an unauthenticated WebSocket.
    """
    header_token = _bearer_from_header(websocket.headers.get("Authorization"))
    return header_token or websocket.query_params.get("access_token")
