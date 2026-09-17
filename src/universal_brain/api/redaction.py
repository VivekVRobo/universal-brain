"""
Universal Brain - Evidence Redaction Filter

Backend-side secret and credential sanitizer.
Strictly ensures that API keys, tokens, private keys, and authorization headers
are redacted before raw evidence or logs are transmitted to the Operator Console.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Union


# Common secret patterns
REDACTION_PATTERNS = [
    # OpenAI / Anthropic / Generic API keys
    (r"(sk-[a-zA-Z0-9_-]{20,})", "[REDACTED_API_KEY]"),
    (r"(sk-ant-[a-zA-Z0-9_-]{20,})", "[REDACTED_ANTHROPIC_KEY]"),
    (r"(AIzaSy[a-zA-Z0-9_-]{33})", "[REDACTED_GOOGLE_KEY]"),
    # Bearer tokens & JWTs
    (r"Bearer\s+[a-zA-Z0-9\._-]{20,}", "Bearer [REDACTED_TOKEN]"),
    (r"ey[a-zA-Z0-9_-]{10,}\.ey[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}", "[REDACTED_JWT]"),
    # Private Keys & Passwords
    (r"-----BEGIN\s+[A-Z\s]+PRIVATE\s+KEY-----[\s\S]+?-----END\s+[A-Z\s]+PRIVATE\s+KEY-----", "[REDACTED_PRIVATE_KEY]"),
    (r"(password|passwd|secret|token)[\"']?\s*[:=]\s*[\"']?[^\s,\"'}]+", r"\1: [REDACTED]"),
    # Telegram Bot Token
    (r"\b\d{9,10}:[a-zA-Z0-9_-]{35}\b", "[REDACTED_TELEGRAM_TOKEN]"),
]


def redact_text(text: str) -> str:
    """Scrub sensitive credentials, keys, and tokens from text content."""
    if not isinstance(text, str):
        return text

    sanitized = text
    for pattern, replacement in REDACTION_PATTERNS:
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)
    return sanitized


def redact_evidence_payload(payload: Union[Dict[str, Any], List[Any], str, Any]) -> Any:
    """Recursively scrub sensitive keys from arbitrary JSON/dict evidence structures."""
    if isinstance(payload, str):
        return redact_text(payload)

    if isinstance(payload, dict):
        sanitized_dict = {}
        for k, v in payload.items():
            # Redact key value if key matches sensitive naming
            if any(secret_term in k.lower() for secret_term in ["secret", "password", "token", "auth", "api_key", "private_key"]):
                sanitized_dict[k] = "[REDACTED]"
            else:
                sanitized_dict[k] = redact_evidence_payload(v)
        return sanitized_dict

    if isinstance(payload, list):
        return [redact_evidence_payload(item) for item in payload]

    return payload
