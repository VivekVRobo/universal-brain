"""
Universal Brain - Ephemeral Worker Authentication Service

Implements Gate S1 Two-Token Worker Authentication Model:
1. Worker Session Token: Issued upon worker enrollment for polling.
   Bound to {worker_id, session_id, kernel_epoch, allowed_type, expiry}.
2. Job Lease Token: Issued upon job assignment for progress and completion.
   Bound to {worker_id, session_id, job_id, lease_generation, kernel_epoch, body_digest, expiry}.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Dict, Optional

from universal_brain.config import settings
from universal_brain.kernel.errors import CapabilityDeniedError


class WorkerAuthService:
    """Issues and validates worker session and job lease credentials."""

    def __init__(self, secret_key: Optional[str] = None) -> None:
        self._secret = (secret_key or settings.hmac_secret_key).encode("utf-8")

    # -------------------------------------------------------------------------
    # 1. Worker Session Tokens (Polling)
    # -------------------------------------------------------------------------

    def generate_worker_session_token(
        self,
        worker_id: str,
        session_id: str,
        kernel_epoch: int = 1,
        allowed_type: str = "generic",
        ttl_seconds: int = 3600,
    ) -> str:
        """Issues time-bounded token: WSESS:{worker_id}:{session_id}:{epoch}:{type}:{expiry}:{signature}."""
        expiry = int(time.time()) + ttl_seconds
        payload = f"WSESS:{worker_id}:{session_id}:{kernel_epoch}:{allowed_type}:{expiry}"
        sig = hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{payload}:{sig}"

    def verify_worker_session_token(
        self,
        token: str,
        expected_worker_id: Optional[str] = None,
        expected_session_id: Optional[str] = None,
        current_epoch: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Validates worker session token signature, expiry, and identity claims."""
        parts = token.split(":")
        # Check if legacy 4-part token or new WSESS 7-part token
        if len(parts) == 4:
            # Legacy format: {worker_id}:{session_id}:{expiry}:{sig}
            worker_id, session_id, expiry_str, sig = parts
            payload = f"{worker_id}:{session_id}:{expiry_str}"
            expected_sig = hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected_sig):
                raise CapabilityDeniedError("Worker session token HMAC signature mismatch.")
            try:
                expiry = int(expiry_str)
            except ValueError:
                raise CapabilityDeniedError("Worker token has invalid expiry.")
            if time.time() > expiry:
                raise CapabilityDeniedError("Worker session authentication token has expired.")
            epoch = 1
            allowed_type = "generic"
        elif len(parts) == 7 and parts[0] == "WSESS":
            _, worker_id, session_id, epoch_str, allowed_type, expiry_str, sig = parts
            payload = f"WSESS:{worker_id}:{session_id}:{epoch_str}:{allowed_type}:{expiry_str}"
            expected_sig = hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected_sig):
                raise CapabilityDeniedError("Worker session token HMAC signature mismatch.")
            try:
                expiry = int(expiry_str)
                epoch = int(epoch_str)
            except ValueError:
                raise CapabilityDeniedError("Worker session token contains non-integer claims.")
            if time.time() > expiry:
                raise CapabilityDeniedError("Worker session authentication token has expired.")
        else:
            raise CapabilityDeniedError("Invalid worker session token format.")

        # Match bound identity claims
        if expected_worker_id and worker_id != expected_worker_id:
            raise CapabilityDeniedError(
                f"Worker session token was issued to '{worker_id}', cannot be used by '{expected_worker_id}'."
            )
        if expected_session_id and session_id != expected_session_id:
            raise CapabilityDeniedError("Worker session token session_id mismatch.")
        if current_epoch and epoch != current_epoch:
            raise CapabilityDeniedError(
                f"Worker session token epoch {epoch} is stale; current kernel epoch is {current_epoch}."
            )

        return {
            "worker_id": worker_id,
            "session_id": session_id,
            "kernel_epoch": epoch,
            "allowed_type": allowed_type,
            "expires_at": expiry,
        }

    # -------------------------------------------------------------------------
    # 2. Job Lease Tokens (Progress & Completion)
    # -------------------------------------------------------------------------

    def generate_job_lease_token(
        self,
        worker_id: str,
        session_id: str,
        job_id: str,
        lease_generation: int,
        kernel_epoch: int = 1,
        body_digest: str = "*",
        ttl_seconds: int = 3600,
    ) -> str:
        """Issues lease token: WLEASE:{worker_id}:{session_id}:{job_id}:{gen}:{epoch}:{digest}:{expiry}:{sig}."""
        expiry = int(time.time()) + ttl_seconds
        payload = f"WLEASE:{worker_id}:{session_id}:{job_id}:{lease_generation}:{kernel_epoch}:{body_digest}:{expiry}"
        sig = hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{payload}:{sig}"

    def verify_job_lease_token(
        self,
        token: str,
        expected_worker_id: str,
        expected_job_id: str,
        expected_lease_generation: int,
        expected_session_id: Optional[str] = None,
        current_epoch: Optional[int] = None,
        body_digest: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validates job lease token signature, expiry, and all 5 bound parameters."""
        parts = token.split(":")
        if len(parts) != 9 or parts[0] != "WLEASE":
            raise CapabilityDeniedError("Invalid job lease token format.")

        _, worker_id, session_id, job_id, gen_str, epoch_str, digest, expiry_str, sig = parts
        payload = f"WLEASE:{worker_id}:{session_id}:{job_id}:{gen_str}:{epoch_str}:{digest}:{expiry_str}"
        expected_sig = hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(sig, expected_sig):
            raise CapabilityDeniedError("Job lease token HMAC signature mismatch.")

        try:
            expiry = int(expiry_str)
            gen = int(gen_str)
            epoch = int(epoch_str)
        except ValueError:
            raise CapabilityDeniedError("Job lease token contains non-integer claims.")

        if time.time() > expiry:
            raise CapabilityDeniedError("Job lease authentication token has expired.")

        # Verify all bound dimensions
        if worker_id != expected_worker_id:
            raise CapabilityDeniedError(
                f"Job lease token belongs to worker '{worker_id}', attempted use by '{expected_worker_id}'."
            )
        if job_id != expected_job_id:
            raise CapabilityDeniedError(
                f"Job lease token belongs to job '{job_id}', attempted use on job '{expected_job_id}'."
            )
        if gen != expected_lease_generation:
            raise CapabilityDeniedError(
                f"Job lease token generation {gen} does not match active generation {expected_lease_generation}."
            )
        if expected_session_id and session_id != expected_session_id:
            raise CapabilityDeniedError("Job lease token session_id mismatch.")
        if current_epoch and epoch != current_epoch:
            raise CapabilityDeniedError(
                f"Job lease token epoch {epoch} is stale; current kernel epoch is {current_epoch}."
            )
        if digest != "*" and body_digest and digest != body_digest:
            raise CapabilityDeniedError("Job lease token body digest mismatch: request payload has been tampered with.")

        return {
            "worker_id": worker_id,
            "session_id": session_id,
            "job_id": job_id,
            "lease_generation": gen,
            "kernel_epoch": epoch,
            "body_digest": digest,
            "expires_at": expiry,
        }

    # -------------------------------------------------------------------------
    # Backward Compatibility
    # -------------------------------------------------------------------------

    def generate_worker_token(self, worker_id: str, session_id: str, ttl_seconds: int = 86400) -> str:
        """Backward compatible session token generator."""
        return self.generate_worker_session_token(worker_id, session_id, ttl_seconds=ttl_seconds)

    def verify_worker_token(self, token: str) -> bool:
        """Backward compatible session token verifier."""
        self.verify_worker_session_token(token)
        return True
