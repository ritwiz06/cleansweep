import http.server
import json
import threading

import pytest

USAGE = {"prompt_tokens": 900, "completion_tokens": 50}
REPLY = {"choices": [{"message": {"content": "ok"}}], "usage": USAGE}


@pytest.fixture
def upstream():
    """A local stand-in for the LLM endpoint: records each request (method, path,
    Authorization header, body) and answers chat requests with REPLY (500 when the body asks)."""
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def reply(self, status, body):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_GET(self):
            seen.append(("GET", self.path, self.headers.get("Authorization"), b""))
            self.reply(200, {"id": "model_a", "max_input_tokens": 262144})

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            seen.append(("POST", self.path, self.headers.get("Authorization"), body))
            failing = b"fail" in body
            self.reply(500 if failing else 200, {"error": "boom"} if failing else REPLY)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1", seen
    server.shutdown()
    server.server_close()
