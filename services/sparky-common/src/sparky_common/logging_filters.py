"""Logging filters — PLAN.md §10 (redact *_KEY / *_TOKEN / *_SECRET, Bearer tokens)."""

from __future__ import annotations

import logging
import re

# Conservative patterns for structured log lines (full redaction lands with gateway PR).
_BEARER = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)(\S+)")
_INLINE_SECRET = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:KEY|TOKEN|SECRET))\s*=\s*(\S+)",
)


class RedactSecretsFilter(logging.Filter):
    """Strip obvious secret material from log records before emission."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 — logging.Filter API
        msg = record.msg
        if isinstance(msg, str):
            msg = _BEARER.sub(r"\1[REDACTED]", msg)
            msg = _INLINE_SECRET.sub(lambda m: f"{m.group(1)}=[REDACTED]", msg)
            record.msg = msg
        return True
