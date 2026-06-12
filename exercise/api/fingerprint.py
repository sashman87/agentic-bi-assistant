"""User identity helpers.

The user_id is derived entirely client-side:
  SHA-256( browser_fingerprint + localStorage_UUID )

The server treats it as an opaque, non-secret identifier used only to isolate
conversation history. No authentication, no passwords — just isolation so that
different users on different machines cannot access each other's conversations.
"""
from __future__ import annotations


def validate_user_id(user_id: str) -> str:
    """Validate that user_id is a non-empty string. Returns it stripped."""
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id must be a non-empty string")
    return user_id.strip()
