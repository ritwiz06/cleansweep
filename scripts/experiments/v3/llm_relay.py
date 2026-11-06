"""A host-side relay between Aider's container and the LLM endpoint, so the key never enters
the container: the container talks to the relay with a dummy key, and the relay forwards its
chat requests with the real key added. Also the endpoint's context window for the model."""

from __future__ import annotations

import http.server
import json
import threading
import time
import urllib.error
import urllib.request

REQUEST_TIMEOUT_S = 600  # the LLM client's timeout_s
DEFAULT_CONTEXT = 32768  # input tokens, when the endpoint does not report the model's
RELAY_HOST = "host.docker.internal"  # the host, from a Docker Desktop container


class Relay:
    """A host-side relay for one Aider run: forwards POST /v1/chat/completions to the endpoint
    with the key added and the reply passed through unchanged; refuses every other path and
    method. It logs no header or body; it records each request's status, seconds and token
    counts, the run's count of LLM requests."""

    PATH = "/v1/chat/completions"

    def __init__(self, base_url: str, key: str, timeout_s: float = REQUEST_TIMEOUT_S + 60):
        self.target = base_url.rstrip("/") + "/chat/completions"
        self.key, self.timeout_s = key, timeout_s
        self.requests: list[dict] = []
        relay = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 (the base class's naming)
                relay.forward(self)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.url = f"http://{RELAY_HOST}:{self.port}/v1"

    def __enter__(self) -> Relay:
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()

    def forward(self, handler: http.server.BaseHTTPRequestHandler) -> None:
        if handler.path != self.PATH:
            handler.send_error(403)
            return
        body = handler.rfile.read(int(handler.headers.get("Content-Length") or 0))
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"}
        request = urllib.request.Request(self.target, data=body, headers=headers, method="POST")
        record, start, sent = {"t": round(time.time(), 2)}, time.time(), False
        try:
            try:
                response = urllib.request.urlopen(request, timeout=self.timeout_s)
            except urllib.error.HTTPError as err:
                response = err  # an error reply passes through as it came
            with response:
                handler.send_response(response.status)
                sent = True
                handler.send_header("Content-Type", response.headers.get("Content-Type", ""))
                handler.end_headers()  # HTTP/1.0: the body ends when the connection closes
                chunks = []
                while chunk := response.read(65536):
                    handler.wfile.write(chunk)
                    chunks.append(chunk)
            record["status"] = response.status
            record.update(_usage(b"".join(chunks)))
        except OSError as exc:  # the endpoint unreachable or timed out
            record["error"] = type(exc).__name__
            if not sent:
                handler.send_error(502)
        finally:
            record["seconds"] = round(time.time() - start, 2)
            self.requests.append(record)


def _usage(body: bytes) -> dict:
    try:
        usage = json.loads(body).get("usage") or {}
    except (ValueError, AttributeError):
        return {}
    return {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens")}


def context_window(base_url: str, key: str, model: str) -> dict:
    """The model's input (and output) token limits as the endpoint's /models entry reports
    them, else DEFAULT_CONTEXT input tokens; with where they came from."""
    url = f"{base_url.rstrip('/')}/models/{model}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            entry = json.loads(response.read())
    except (OSError, ValueError):
        entry = {}
    found = entry.get("max_input_tokens") or entry.get("context_window")
    found = found or entry.get("max_model_len")
    info = {"max_input_tokens": int(found or DEFAULT_CONTEXT)}
    if entry.get("max_output_tokens"):
        info["max_output_tokens"] = int(entry["max_output_tokens"])
    source = "the endpoint's /models entry" if found else f"not reported: {DEFAULT_CONTEXT}"
    return {**info, "source": source}
