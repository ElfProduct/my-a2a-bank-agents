"""Tool that lets the personal agent talk to the bank's customer service
agent over A2A, propagating the current session's contextId so both agents
(and the env) share one conversation identity."""

import os
import sys
import time
import uuid

import httpx
from a2a.client import ClientConfig, ClientFactory, minimal_agent_card
from a2a.types import Message, Part, Role, Task, TextPart
from google.adk.tools import ToolContext

from env_toolset import session_id

CS_AGENT_URL = os.environ["CS_AGENT_URL"]

_TIMEOUT_S = 300.0
_PREVIEW_CHARS = 120


def _preview(text: str) -> str:
    return " ".join(text.split())[:_PREVIEW_CHARS]


def _text_of_message(message: Message) -> str:
    texts = []
    for part in message.parts or []:
        root = getattr(part, "root", part)
        if isinstance(root, TextPart) and root.text:
            texts.append(root.text)
    return "\n".join(texts)


def _text_of_task(task: Task) -> str:
    texts = []
    for artifact in task.artifacts or []:
        for part in artifact.parts or []:
            root = getattr(part, "root", part)
            if isinstance(root, TextPart) and root.text:
                texts.append(root.text)
    if task.status is not None and task.status.message is not None:
        text = _text_of_message(task.status.message)
        if text:
            texts.append(text)
    return "\n".join(texts)


async def ask_customer_service(message: str, tool_context: ToolContext) -> str:
    """Send a message to the bank's customer service agent and return its reply.

    The conversation with customer service persists for this whole session,
    so you can ask follow-up questions and they will remember the context.
    """
    sid = session_id(tool_context)
    start = time.perf_counter()
    print(
        f"[personal.cs] context={sid} send preview={_preview(message)!r}",
        file=sys.stderr,
        flush=True,
    )
    outgoing = Message(
        message_id=uuid.uuid4().hex,
        role=Role.user,
        parts=[Part(root=TextPart(text=message))],
        context_id=sid,
    )
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as http_client:
            client = ClientFactory(
                ClientConfig(streaming=False, httpx_client=http_client)
            ).create(minimal_agent_card(CS_AGENT_URL, ["JSONRPC"]))
            reply = ""
            async for event in client.send_message(outgoing):
                if isinstance(event, Message):
                    reply = _text_of_message(event) or reply
                elif isinstance(event, tuple) and isinstance(event[0], Task):
                    reply = _text_of_task(event[0]) or reply
        elapsed = time.perf_counter() - start
        print(
            f"[personal.cs] context={sid} done elapsed={elapsed:.2f}s "
            f"reply_chars={len(reply)}",
            file=sys.stderr,
            flush=True,
        )
        return reply or "[no response from customer service]"
    except Exception as exc:
        elapsed = time.perf_counter() - start
        print(
            f"[personal.cs] context={sid} error elapsed={elapsed:.2f}s "
            f"type={type(exc).__name__}",
            file=sys.stderr,
            flush=True,
        )
        raise
