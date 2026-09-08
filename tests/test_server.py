import base64
import http.client
import io
import json
import re
import threading
import zipfile

import pytest

from forecast_review_workbench.example import example_request
from forecast_review_workbench.server import WorkbenchServer, load_json


@pytest.fixture
def local_tool():
    server = WorkbenchServer(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def request(server, path="/", method="GET", payload=None, headers=None, raw=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    body = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
    connection.request(method, path, body, headers or {})
    response = connection.getresponse()
    status, response_headers, content = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return status, response_headers, content


def browser_headers(server):
    status, headers, html = request(server)
    assert status == 200
    match = re.search(rb'<meta name="csrf-token" content="([a-f0-9]{64})">', html)
    assert match, "The actual served HTML must contain the request token."
    assert headers["Cache-Control"] == "no-store"
    return {"Content-Type": "application/json", "X-Workbench-Token": match[1].decode(), "Origin": server.url}


def test_real_browser_protocol_inspects_reviews_and_downloads(local_tool):
    headers = browser_headers(local_tool)
    sample = example_request()
    status, _, raw = request(local_tool, "/api/inspect", "POST", {"file": sample["actual"]["file"]}, headers)
    assert status == 200
    assert json.loads(raw)["headers"] == ["Month", "Observed"]
    status, _, raw = request(local_tool, "/api/review", "POST", sample, headers)
    assert status == 200
    result = json.loads(raw)
    assert result["summary"]["common"] == 7 and not result["comparison_ready"]
    sample["accept_common_sample"] = True
    status, _, raw = request(local_tool, "/api/review", "POST", sample, headers)
    result = json.loads(raw)
    assert status == 200 and result["comparison_ready"]
    export = {"request": sample, "fingerprint": result["fingerprint"], "notes": []}
    status, response_headers, raw = request(local_tool, "/api/export", "POST", export, headers)
    assert status == 200 and response_headers["Content-Type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert json.loads(archive.read("results.json"))["fingerprint"] == result["fingerprint"]
    export["request"]["actual"]["source_note"] += " revised"
    status, _, raw = request(local_tool, "/api/export", "POST", export, headers)
    assert status == 400 and "changed" in json.loads(raw)["error"]


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Host": "attacker.example"},
        {"Origin": "https://attacker.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_foreign_or_tokenless_posts_cannot_access_inputs(local_tool, headers):
    supplied = {"Content-Type": "application/json", **headers}
    if headers:
        supplied["X-Workbench-Token"] = browser_headers(local_tool)["X-Workbench-Token"]
    status, response_headers, _ = request(local_tool, "/api/review", "POST", example_request(), supplied)
    assert status == 403
    assert "Access-Control-Allow-Origin" not in response_headers


def test_no_arbitrary_files_or_origin_reflection(local_tool):
    for path in ("/../README.md", "/static/../../LICENSE", "/.git/config", "/engine.py"):
        assert request(local_tool, path)[0] == 404
    assert request(local_tool, headers={"Host": "localhost.attacker.example"})[0] == 403
    assert request(local_tool, "/api/review", "OPTIONS")[0] == 403
    assert local_tool.server_address[0] == "127.0.0.1"


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"x":NaN}', b"[]", b"null", b"\xff"])
def test_ambiguous_or_invalid_json_is_rejected(raw):
    with pytest.raises(ValueError):
        load_json(raw)


def test_input_file_cannot_name_a_server_path(local_tool):
    headers = browser_headers(local_tool)
    payload = {"file": {"path": "/etc/passwd", "name": "test.csv"}}
    status, _, _ = request(local_tool, "/api/inspect", "POST", payload, headers)
    assert status == 400
    payload = {"file": {"name": "arbitrary.csv", "content_base64": base64.b64encode(b"x,y\n1,2\n").decode()}}
    assert request(local_tool, "/api/inspect", "POST", payload, headers)[0] == 200
