import os
from unittest import mock

import server


def test_api_key_env_var_priority():
    # 1. When env var is present
    with mock.patch.dict(os.environ, {"OMNIDIM_API_KEY": "env-test-key-123456"}):
        key, source = server.get_api_key()
        assert key == "env-test-key-123456"
        assert source == "env"

        settings = server.read_settings(include_secret=True)
        assert settings["apiKey"] == "env-test-key-123456"
        assert settings["apiKeySource"] == "env"
        assert "environment variable" in settings["securityNotice"]


def test_redact_payload_recursive():
    payload = {
        "Name": "John",
        "api_key": "secret-123",
        "nested": {
            "AUTH_TOKEN": "token-xyz",
            "sip_password": "super-sip-secret",
            "account_sid": "AC1234567890",
            "normal_field": 42,
        },
        "list_items": [
            {"user": "Alice", "password": "alice-password"},
            {"user": "Bob", "token": "bearer-bob"},
        ],
    }
    redacted = server.redact_payload(payload)

    assert redacted["Name"] == "John"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["AUTH_TOKEN"] == "[REDACTED]"
    assert redacted["nested"]["sip_password"] == "[REDACTED]"
    assert redacted["nested"]["account_sid"] == "[REDACTED]"
    assert redacted["nested"]["normal_field"] == 42
    assert redacted["list_items"][0]["password"] == "[REDACTED]"
    assert redacted["list_items"][1]["token"] == "[REDACTED]"


def test_redact_large_base64_file():
    payload = {
        "filename": "document.pdf",
        "file": "JVBERi0xLjQKJcTl8uXr...very-long-base64-string-over-100-characters" * 10,
    }
    redacted = server.redact_payload(payload)
    assert redacted["filename"] == "document.pdf"
    assert "BASE64_FILE:" in redacted["file"]
    assert "redacted" in redacted["file"]


def test_sanitize_url_removes_secrets():
    raw_url = "https://omnidim.io/api/v1/resource?normal=1&api_key=secret-val&token=abc"
    clean = server.sanitize_url(raw_url)
    assert "normal=1" in clean
    assert "secret-val" not in clean
    assert "abc" not in clean
    assert "api_key=%5BREDACTED%5D" in clean or "api_key=[REDACTED]" in clean


def test_history_logging_redaction_and_retention():
    server.init_db()
    with server.get_db() as conn:
        conn.execute("DELETE FROM request_history")

    # Log an entry with sensitive payload
    sensitive_req = {"api_key": "my-secret-key", "action": "test"}
    sensitive_res = {"token": "returned-token", "ok": True}
    sensitive_url = "https://omnidim.io/api/v1/test?token=query-secret"

    server.log_history(
        "test-ep",
        "POST",
        "/test",
        sensitive_url,
        200,
        True,
        15,
        sensitive_req,
        sensitive_res,
    )

    with server.get_db() as conn:
        row = conn.execute("SELECT * FROM request_history ORDER BY id DESC LIMIT 1").fetchone()
        assert row is not None
        assert "my-secret-key" not in row["request_json"]
        assert "[REDACTED]" in row["request_json"]
        assert "returned-token" not in row["response_json"]
        assert "[REDACTED]" in row["response_json"]
        assert "query-secret" not in row["url"]


def test_history_auto_prune_limit():
    server.init_db()
    with server.get_db() as conn:
        conn.execute("DELETE FROM request_history")
        # Insert 505 rows directly
        conn.executemany(
            """
            INSERT INTO request_history
            (endpoint_id, method, path, url, status, ok, duration_ms, request_json, response_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [("ep", "GET", "/", "/", 200, 1, 1, "{}", "{}", "2026-01-01T00:00:00Z") for _ in range(505)],
        )

    # Calling log_history should prune to retention limit (500)
    server.log_history("ep", "GET", "/", "/", 200, True, 1, {}, {})

    with server.get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM request_history").fetchone()[0]
        assert count == server.HISTORY_RETENTION_LIMIT
