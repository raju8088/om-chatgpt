import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

import server


@pytest.fixture(scope="module")
def live_server():
    server.init_db()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
    host, port = httpd.server_address
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"{host}:{port}", port
    httpd.shutdown()
    httpd.server_close()


def test_host_header_rejection(live_server):
    host_port, port = live_server
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/api/endpoints", headers={"Host": "attacker.com"})
    res = conn.getresponse()
    body = json.loads(res.read().decode())
    conn.close()

    assert res.status == 403
    assert body["ok"] is False
    assert "Host" in body["error"]
    assert "requestId" in body


def test_host_header_allowed(live_server):
    host_port, port = live_server
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/api/endpoints", headers={"Host": f"127.0.0.1:{port}"})
    res = conn.getresponse()
    body = json.loads(res.read().decode())
    conn.close()

    assert res.status == 200
    assert "groups" in body


def test_content_type_enforcement_on_mutating_requests(live_server):
    host_port, port = live_server
    conn = http.client.HTTPConnection("127.0.0.1", port)
    # Missing content-type on POST
    conn.request(
        "POST",
        "/api/settings",
        body=b'{"baseUrl":"https://omnidim.io/api/v1"}',
        headers={"Host": f"127.0.0.1:{port}"},
    )
    res = conn.getresponse()
    body = json.loads(res.read().decode())
    conn.close()

    assert res.status == 415
    assert "Content-Type must be application/json" in body["error"]
    assert "requestId" in body


def test_origin_header_validation(live_server):
    host_port, port = live_server
    conn = http.client.HTTPConnection("127.0.0.1", port)
    # Invalid Origin
    conn.request(
        "POST",
        "/api/settings",
        body=b'{"baseUrl":"https://omnidim.io/api/v1"}',
        headers={
            "Host": f"127.0.0.1:{port}",
            "Content-Type": "application/json",
            "Origin": "http://evil-attacker.com",
            "X-CSRF-Token": server.CSRF_TOKEN,
        },
    )
    res = conn.getresponse()
    body = json.loads(res.read().decode())
    conn.close()

    assert res.status == 403
    assert "Cross-origin" in body["error"]


def test_csrf_token_enforcement(live_server):
    host_port, port = live_server

    # 1. Missing CSRF token
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request(
        "POST",
        "/api/settings",
        body=b'{"baseUrl":"https://omnidim.io/api/v1"}',
        headers={
            "Host": f"127.0.0.1:{port}",
            "Content-Type": "application/json",
            "Origin": f"http://127.0.0.1:{port}",
        },
    )
    res = conn.getresponse()
    body = json.loads(res.read().decode())
    conn.close()
    assert res.status == 403
    assert "CSRF" in body["error"]

    # 2. Invalid CSRF token
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request(
        "POST",
        "/api/settings",
        body=b'{"baseUrl":"https://omnidim.io/api/v1"}',
        headers={
            "Host": f"127.0.0.1:{port}",
            "Content-Type": "application/json",
            "Origin": f"http://127.0.0.1:{port}",
            "X-CSRF-Token": "bogus-csrf-token",
        },
    )
    res = conn.getresponse()
    body = json.loads(res.read().decode())
    conn.close()
    assert res.status == 403
    assert "CSRF" in body["error"]

    # 3. Valid CSRF token
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request(
        "POST",
        "/api/settings",
        body=b'{"baseUrl":"https://omnidim.io/api/v1"}',
        headers={
            "Host": f"127.0.0.1:{port}",
            "Content-Type": "application/json",
            "Origin": f"http://127.0.0.1:{port}",
            "X-CSRF-Token": server.CSRF_TOKEN,
        },
    )
    res = conn.getresponse()
    body = json.loads(res.read().decode())
    conn.close()
    assert res.status == 200
    assert body["baseUrl"] == "https://omnidim.io/api/v1"


def test_session_endpoint_returns_csrf(live_server):
    host_port, port = live_server
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/api/session", headers={"Host": f"127.0.0.1:{port}"})
    res = conn.getresponse()
    body = json.loads(res.read().decode())
    conn.close()

    assert res.status == 200
    assert body["ok"] is True
    assert body["csrfToken"] == server.CSRF_TOKEN


def test_options_no_cors_headers(live_server):
    host_port, port = live_server
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("OPTIONS", "/api/run", headers={"Host": f"127.0.0.1:{port}"})
    res = conn.getresponse()
    headers = dict(res.getheaders())
    conn.close()

    assert res.status == 204
    for header in headers:
        assert not header.lower().startswith("access-control-")


def test_static_security_headers_and_csrf_injection(live_server):
    host_port, port = live_server
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/", headers={"Host": f"127.0.0.1:{port}"})
    res = conn.getresponse()
    body = res.read().decode()
    opt = res.getheader("x-content-type-options")
    frame = res.getheader("x-frame-options")
    ref = res.getheader("referrer-policy")
    csp = res.getheader("content-security-policy")
    conn.close()

    assert res.status == 200
    assert opt == "nosniff"
    assert frame == "DENY"
    assert ref == "no-referrer"
    assert "default-src 'self'" in (csp or "")
    assert f'<meta name="csrf-token" content="{server.CSRF_TOKEN}">' in body


def test_static_path_traversal_prevention(live_server):
    host_port, port = live_server
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/static/../../server.py", headers={"Host": f"127.0.0.1:{port}"})
    res = conn.getresponse()
    conn.close()

    # Must be rejected with 403 or 404, never 200 returning server.py
    assert res.status in (403, 404)
