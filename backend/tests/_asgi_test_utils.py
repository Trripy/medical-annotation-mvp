from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from urllib.parse import urlencode


@dataclass(frozen=True)
class ASGIResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8")

    def json(self):
        return json.loads(self.body.decode("utf-8"))


async def _asgi_request_async(
    app,
    method: str,
    path: str,
    *,
    params: dict[str, object] | None = None,
    json_body: dict[str, object] | None = None,
    timeout_seconds: float = 5.0,
) -> ASGIResponse:
    request_body = b""
    headers: list[tuple[bytes, bytes]] = []
    if json_body is not None:
        request_body = json.dumps(json_body).encode("utf-8")
        headers.extend(
            [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(request_body)).encode("ascii")),
            ]
        )

    query_string = urlencode(params or {}, doseq=True).encode("utf-8")
    messages: list[dict] = []
    response_complete = asyncio.Event()
    request_sent = False

    async def receive() -> dict:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {
                "type": "http.request",
                "body": request_body,
                "more_body": False,
            }

        if response_complete.is_set():
            return {"type": "http.disconnect"}

        try:
            await asyncio.wait_for(response_complete.wait(), timeout=0.01)
        except asyncio.TimeoutError:
            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)
        if message["type"] == "http.response.body" and not message.get("more_body", False):
            response_complete.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query_string,
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "root_path": "",
        "app": app,
    }

    await asyncio.wait_for(app(scope, receive, send), timeout=timeout_seconds)

    response_start = next(
        (message for message in messages if message["type"] == "http.response.start"),
        None,
    )
    if response_start is None:
        raise AssertionError("ASGI app did not send an http.response.start message.")

    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    response_headers = {
        key.decode("latin1"): value.decode("latin1")
        for key, value in response_start.get("headers", [])
    }
    return ASGIResponse(
        status_code=response_start["status"],
        headers=response_headers,
        body=response_body,
    )


def asgi_request(
    app,
    method: str,
    path: str,
    *,
    params: dict[str, object] | None = None,
    json_body: dict[str, object] | None = None,
    timeout_seconds: float = 5.0,
) -> ASGIResponse:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            _asgi_request_async(
                app,
                method,
                path,
                params=params,
                json_body=json_body,
                timeout_seconds=timeout_seconds,
            )
        )
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
