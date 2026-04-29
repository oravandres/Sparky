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
        # Expand %-formatting first so secrets smuggled only in record.args are visible,
        # then replace whole message and clear args so formatters cannot re-expand secrets.
        text = record.getMessage()
        redacted = _BEARER.sub(r"\1[REDACTED]", text)
        redacted = _INLINE_SECRET.sub(lambda m: f"{m.group(1)}=[REDACTED]", redacted)
        record.msg = redacted
        record.args = ()
        return True
