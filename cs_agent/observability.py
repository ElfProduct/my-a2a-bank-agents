"""Local JSON-line observability for latency and failure triage."""

from __future__ import annotations

import contextvars
import datetime as dt
import json
import os
import re
import sys
import time
from typing import Any
from urllib.parse import urlparse

_context_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "observability_context_id", default=None
)
_httpx_installed = False


def enabled() -> bool:
    return os.environ.get("OBSERVABILITY_ENABLED", "1").lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def current_context_id() -> str | None:
    return _context_id.get()


def _truncate(value: Any, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = str(value)
    key = os.environ.get("GOOGLE_API_KEY")
    if key:
        text = text.replace(key, "[redacted]")
    text = re.sub(r"([?&]key=)[^&\s]+", r"\1[redacted]", text)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _clean(fields: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in fields.items() if v is not None}


def set_context_id(value: str | None):
    if not value:
        return None
    return _context_id.set(value)


def reset_context_id(token) -> None:
    if token is not None:
        _context_id.reset(token)


class use_context:
    def __init__(self, value: str | None):
        self._value = value
        self._token = None

    def __enter__(self):
        self._token = set_context_id(self._value)
        return self

    def __exit__(self, exc_type, exc, tb):
        reset_context_id(self._token)
        return False


def log_event(event: str, agent_name: str, **fields: Any) -> None:
    if not enabled():
        return
    context_id = fields.pop("context_id", None) or current_context_id()
    record = _clean(
        {
            "event": event,
            "agent": agent_name,
            "ts": utc_now(),
            "context_id": context_id,
            **fields,
        }
    )
    print("[obs] " + json.dumps(record, sort_keys=True, default=str), file=sys.stderr, flush=True)


def start_observation(event: str, agent_name: str, **fields: Any) -> dict[str, Any]:
    start_ts = utc_now()
    span = {
        "event": event,
        "agent_name": agent_name,
        "start_ts": start_ts,
        "start_perf": time.perf_counter(),
        "fields": fields,
    }
    log_event(f"{event}.start", agent_name, start_ts=start_ts, **fields)
    return span


def finish_observation(
    span: dict[str, Any],
    *,
    success: bool,
    exception: BaseException | None = None,
    **fields: Any,
) -> None:
    end_ts = utc_now()
    duration_ms = round((time.perf_counter() - span["start_perf"]) * 1000, 1)
    exc_fields = exception_fields(exception) if exception is not None else {}
    log_event(
        f"{span['event']}.end",
        span["agent_name"],
        start_ts=span["start_ts"],
        end_ts=end_ts,
        duration_ms=duration_ms,
        success=success,
        **span["fields"],
        **fields,
        **exc_fields,
    )


def exception_fields(exc: BaseException | None) -> dict[str, Any]:
    if exc is None:
        return {}
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None) if response is not None else None
    return _clean(
        {
            "exception_class": exc.__class__.__name__,
            "exception": _truncate(exc),
            "http_status": status_code or getattr(exc, "status_code", None),
            "google_error_code": getattr(exc, "code", None),
            "google_error_status": getattr(exc, "status", None),
            "retryable": is_retryable_exception(exc),
        }
    )


def is_retryable_exception(exc: BaseException) -> bool:
    name = exc.__class__.__name__.lower()
    return any(part in name for part in ("timeout", "connect", "protocol", "network"))


def _extract_google_error(response) -> dict[str, Any]:
    if response is None or response.status_code < 400:
        return {}
    try:
        payload = response.json()
    except Exception:
        return {}
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return {}
    return _clean(
        {
            "google_error_code": error.get("code"),
            "google_error_status": error.get("status"),
            "google_error_message": _truncate(error.get("message")),
        }
    )


def _model_from_url(path: str) -> str | None:
    match = re.search(r"/models/([^/:]+)", path)
    if match:
        return match.group(1)
    return os.environ.get("MODEL")


def _url_fields(method: str, url: Any) -> dict[str, Any]:
    parsed = urlparse(str(url))
    host = parsed.netloc
    path = parsed.path
    outbound_kind = "http"
    if "generativelanguage.googleapis.com" in host or "aiplatform.googleapis.com" in host:
        outbound_kind = "google_model_api"
    elif host.startswith("localhost") or "host.docker.internal" in host:
        outbound_kind = "local_service"
    return _clean(
        {
            "method": method,
            "url_host": host,
            "url_path": path,
            "outbound_kind": outbound_kind,
            "model": _model_from_url(path),
        }
    )


def install_httpx_observability(agent_name: str) -> None:
    global _httpx_installed
    if _httpx_installed:
        return
    _httpx_installed = True

    import httpx

    original_async = httpx.AsyncClient.request
    original_sync = httpx.Client.request

    async def observed_async_request(self, method, url, *args, **kwargs):
        fields = _url_fields(str(method), url)
        span = start_observation("httpx.request", agent_name, **fields)
        try:
            response = await original_async(self, method, url, *args, **kwargs)
        except Exception as exc:
            finish_observation(span, success=False, exception=exc)
            raise
        finish_observation(
            span,
            success=200 <= response.status_code < 400,
            http_status=response.status_code,
            **_extract_google_error(response),
        )
        return response

    def observed_sync_request(self, method, url, *args, **kwargs):
        fields = _url_fields(str(method), url)
        span = start_observation("httpx.request", agent_name, **fields)
        try:
            response = original_sync(self, method, url, *args, **kwargs)
        except Exception as exc:
            finish_observation(span, success=False, exception=exc)
            raise
        finish_observation(
            span,
            success=200 <= response.status_code < 400,
            http_status=response.status_code,
            **_extract_google_error(response),
        )
        return response

    httpx.AsyncClient.request = observed_async_request
    httpx.Client.request = observed_sync_request


def _find_context_id(obj: Any) -> str | None:
    if isinstance(obj, dict):
        for key in ("contextId", "context_id", "contextID", "session_id", "sessionId"):
            value = obj.get(key)
            if isinstance(value, str) and value:
                return value
        for value in obj.values():
            found = _find_context_id(value)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_context_id(item)
            if found:
                return found
    return None


def context_id_from_body(body: bytes) -> str | None:
    if not body:
        return None
    try:
        payload = json.loads(body)
    except Exception:
        return None
    return _find_context_id(payload)


class ObservabilityMiddleware:
    """ASGI middleware that logs A2A request duration without consuming bodies."""

    def __init__(self, app, *, agent_name: str, model: str | None = None):
        self.app = app
        self.agent_name = agent_name
        self.model = model

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not enabled():
            await self.app(scope, receive, send)
            return

        messages = []
        body_chunks = []
        more_body = True
        while more_body:
            message = await receive()
            messages.append(message)
            if message.get("type") != "http.request":
                more_body = False
                continue
            body_chunks.append(message.get("body", b""))
            more_body = bool(message.get("more_body", False))

        body = b"".join(body_chunks)
        context_id = context_id_from_body(body)
        token = set_context_id(context_id)
        method = scope.get("method")
        path = scope.get("path")
        status_code = None
        span = start_observation(
            "a2a.request",
            self.agent_name,
            context_id=context_id,
            method=method,
            path=path,
            model=self.model,
        )

        async def replay_receive():
            if messages:
                return messages.pop(0)
            return {"type": "http.request", "body": b"", "more_body": False}

        async def observed_send(message):
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = message.get("status")
            await send(message)

        try:
            await self.app(scope, replay_receive, observed_send)
        except Exception as exc:
            finish_observation(span, success=False, exception=exc, http_status=status_code)
            reset_context_id(token)
            raise
        finish_observation(
            span,
            success=status_code is None or 200 <= status_code < 400,
            http_status=status_code,
        )
        reset_context_id(token)
