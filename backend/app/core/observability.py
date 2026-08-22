import json
import logging
from contextvars import ContextVar, Token
from time import perf_counter
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from app.core.redaction import redact


correlation_context: ContextVar[dict[str, str]] = ContextVar(
    "correlation_context", default={}
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **correlation_context.get(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(redact(payload), ensure_ascii=False, default=str)


def configure_structured_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def bind_correlation(**values: str | None) -> Token:
    context = dict(correlation_context.get())
    context.update({key: value for key, value in values.items() if value})
    return correlation_context.set(context)


def reset_correlation(token: Token) -> None:
    correlation_context.reset(token)


REGISTRY = CollectorRegistry()
HTTP_REQUESTS = Counter(
    "xingliu_http_requests_total",
    "HTTP requests",
    ("method", "route", "status"),
    registry=REGISTRY,
)
HTTP_LATENCY = Histogram(
    "xingliu_http_request_duration_seconds",
    "HTTP request latency",
    ("method", "route"),
    registry=REGISTRY,
)
OUTBOX_BACKLOG = Gauge(
    "xingliu_outbox_backlog",
    "Unpublished outbox events",
    registry=REGISTRY,
)
DEAD_LETTERS = Gauge(
    "xingliu_dead_letters",
    "Dead-lettered outbox/consumer events",
    registry=REGISTRY,
)
QUOTA_REJECTS = Counter(
    "xingliu_quota_rejects_total",
    "Hard quota rejects",
    ("metric",),
    registry=REGISTRY,
)


def observe_http(method: str, route: str, status: int, started: float) -> None:
    safe_route = route if route.startswith("/") else "unknown"
    HTTP_REQUESTS.labels(method=method, route=safe_route, status=str(status)).inc()
    HTTP_LATENCY.labels(method=method, route=safe_route).observe(perf_counter() - started)


def metrics_payload() -> bytes:
    return generate_latest(REGISTRY)
