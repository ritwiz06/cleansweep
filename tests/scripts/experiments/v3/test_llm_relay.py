import importlib.util
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "experiments" / "v3" / "llm_relay.py"
# fake credentials, assembled at run time
KEY = "-".join(["fake", "key", "0042"])
DUMMY = "-".join(["dummy", "key"])


def load():
    spec = importlib.util.spec_from_file_location("llm_relay", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def post(port, path, body, method="POST"):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode() if method == "POST" else None,
        headers={"Authorization": f"Bearer {DUMMY}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def test_relay_adds_the_key_and_refuses_other_paths_and_methods(upstream):
    relay_module = load()
    url, seen = upstream
    body = {"model": "openai/model_a", "messages": [{"role": "user", "content": "hi"}]}
    with relay_module.Relay(url, KEY) as relay:
        assert relay.url.startswith("http://host.docker.internal:")
        status, reply = post(relay.port, "/v1/chat/completions", body)
        assert status == 200 and json.loads(reply)["usage"]["prompt_tokens"] == 900
        assert post(relay.port, "/v1/embeddings", body)[0] == 403
        assert post(relay.port, "/v1/models", None, method="GET")[0] == 501
    assert seen == [("POST", "/v1/chat/completions", f"Bearer {KEY}", json.dumps(body).encode())]
    assert [(r["status"], r["prompt_tokens"], r["completion_tokens"]) for r in relay.requests] == [
        (200, 900, 50)
    ]


def test_relay_passes_an_error_reply_through_and_counts_it(upstream):
    relay_module = load()
    url, _ = upstream
    with relay_module.Relay(url, KEY) as relay:
        status, reply = post(relay.port, "/v1/chat/completions", {"messages": "fail"})
    assert (status, json.loads(reply)) == (500, {"error": "boom"})
    assert relay.requests[0]["status"] == 500


@pytest.mark.parametrize("reachable", [True, False])
def test_context_window_from_the_endpoint_or_the_default(upstream, reachable):
    relay_module = load()
    url, seen = upstream
    base = url if reachable else "http://127.0.0.1:9/v1"
    context = relay_module.context_window(base, KEY, "model_a")
    if reachable:
        assert context["max_input_tokens"] == 262144 and "endpoint" in context["source"]
        assert seen == [("GET", "/v1/models/model_a", f"Bearer {KEY}", b"")]
    else:
        assert context == {"max_input_tokens": 32768, "source": "not reported: 32768"}
