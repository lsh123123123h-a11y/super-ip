import re
from typing import Any


SENSITIVE_KEY = re.compile(
    r"(^|[_-])(authorization|api[_-]?key|token|secret|password|cookie|credential)([_-]|$)",
    re.IGNORECASE,
)
BEARER_VALUE = re.compile(r"\b(Bearer|Service)\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if SENSITIVE_KEY.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str):
        return BEARER_VALUE.sub(lambda match: f"{match.group(1)} [REDACTED]", value)
    return value


def safe_error_summary(exc: BaseException, *, limit: int = 1000) -> str:
    return str(redact(f"{type(exc).__name__}: {exc}"))[:limit]
