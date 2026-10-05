import argparse
import datetime as dt
import json
import mimetypes
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "omnidim_ui.sqlite3"
DEFAULT_BASE_URL = "https://omnidim.io/api/v1"
MAX_LOG_CHARS = 200_000


def endpoint_id(method, path):
    return re.sub(r"[^a-z0-9]+", "-", f"{method}-{path}".lower()).strip("-")


def ep(group, method, path, summary, body=None, query=None, note="", danger=False):
    method = method.upper()
    return {
        "id": endpoint_id(method, path),
        "group": group,
        "method": method,
        "path": path,
        "summary": summary,
        "bodyExample": body,
        "queryExample": query or {},
        "note": note,
        "danger": danger,
        "pathParams": re.findall(r"{([^}]+)}", path),
    }


GROUPS = [
    {
        "name": "Sessions",
        "description": "Create temporary browser voice sessions and receive a WebSocket URL.",
        "endpoints": [
            ep("Sessions", "POST", "/sessions/create", "Create session", {"agent_id": 158910}),
        ],
    },
    {
        "name": "Agents",
        "description": "Create, inspect, update, delete, and version AI voice agents.",
        "endpoints": [
            ep("Agents", "GET", "/agents", "List agents", query={"pageno": 1, "pagesize": 30}),
            ep(
                "Agents",
                "POST",
                "/agents/create",
                "Create agent",
                {
                    "name": "Customer Support Agent",
                    "welcome_message": "Hello! I am your support assistant. How can I help you today?",
                    "context_breakdown": [
                        {
                            "title": "Purpose",
                            "body": "This agent helps customers with product questions and support issues.",
                        }
                    ],
                },
            ),
            ep("Agents", "GET", "/agents/{agent_id}", "Get agent"),
            ep(
                "Agents",
                "PUT",
                "/agents/{agent_id}",
                "Update agent",
                {
                    "name": "Updated Support Agent",
                    "welcome_message": "Hello! I am your updated support assistant. How can I help you today?",
                    "context_breakdown": [
                        {
                            "title": "Purpose",
                            "body": "This agent helps customers with product questions and support issues.",
                        }
                    ],
                },
            ),
            ep("Agents", "DELETE", "/agents/{agent_id}", "Delete agent", danger=True),
            ep("Agents", "GET", "/agents/{agent_id}/versions", "List agent versions", query={"pageno": 1, "pagesize": 30}),
            ep(
                "Agents",
                "POST",
                "/agents/{agent_id}/versions",
                "Save an agent version",
                {"name": "Working version", "note": "Saved before editing the prompt."},
            ),
            ep(
                "Agents",
                "PATCH",
                "/agents/{agent_id}/versions/{version_number}",
                "Rename an agent version",
                {"name": "Pre-launch version", "note": "Reviewed and renamed."},
            ),
            ep("Agents", "DELETE", "/agents/{agent_id}/versions/{version_number}", "Delete an agent version", danger=True),
            ep("Agents", "GET", "/agents/{agent_id}/versions/{version_number}/diff", "Diff an agent version"),
            ep(
                "Agents",
                "POST",
                "/agents/{agent_id}/versions/{version_number}/restore",
                "Restore an agent version",
                {},
                danger=True,
            ),
        ],
    },
    {
        "name": "Calls",
        "description": "Place one outbound call and review call logs.",
        "endpoints": [
            ep(
                "Calls",
                "POST",
                "/calls/dispatch",
                "Dispatch call",
                {
                    "agent_id": 158910,
                    "to_number": "+15551234567",
                    "from_number_id": 23,
                    "call_context": {
                        "user_name": "Jane Doe",
                        "account_id": "A-2031",
                        "last_order": "2026-04-15",
                    },
                    "metadata": {"crm_lead_id": "lead_9876", "source": "website_form"},
                },
                danger=True,
                note="This can place a real outbound call when your key has call access.",
            ),
            ep("Calls", "GET", "/calls/logs", "List call logs", query={"page": 1, "page_size": 10}),
            ep("Calls", "GET", "/calls/logs/{call_log_id}", "Get call log"),
        ],
    },
    {
        "name": "Bulk Calls",
        "description": "Build and operate campaign calling flows.",
        "endpoints": [
            ep("Bulk Calls", "GET", "/calls/bulk_call", "Fetch bulk calls", query={"pageno": 1, "pagesize": 10, "status": ""}),
            ep(
                "Bulk Calls",
                "POST",
                "/calls/bulk_call/create",
                "Create bulk call",
                {
                    "name": "Customer follow-ups",
                    "phone_number_id": "177",
                    "bot_id": 512,
                    "contact_list": [
                        {"phone_number": "+15551234567", "customer_name": "John Doe", "plan": "pro"},
                        {"phone_number": "+15559876543", "customer_name": "Jane Smith", "plan": "trial"},
                    ],
                    "is_scheduled": False,
                    "concurrent_call_limit": 1,
                    "retry_config": {"auto_retry": False, "auto_retry_schedule": "next_day", "retry_limit": 1},
                },
                danger=True,
            ),
            ep(
                "Bulk Calls",
                "POST",
                "/calls/bulk_call/{campaign_id}/add_contact",
                "Add contact to dynamic campaign",
                {
                    "to_number": "+15551234567",
                    "custom_variables": {"name": "Demo User", "interest": "Home Insurance"},
                    "metadata": {"crm_lead_id": "lead_9876", "source": "website_form"},
                },
            ),
            ep("Bulk Calls", "GET", "/calls/bulk_call/{bulk_call_id}", "Bulk call details"),
            ep("Bulk Calls", "PUT", "/calls/bulk_call/{bulk_call_id}", "Bulk call actions", {"action": "pause"}),
            ep("Bulk Calls", "DELETE", "/calls/bulk_call/{bulk_call_id}", "Cancel bulk call", danger=True),
            ep("Bulk Calls", "GET", "/calls/bulk_call/{bulk_call_id}/lines", "Bulk call results", query={"pagesize": 150, "include_total": True}),
            ep("Bulk Calls", "GET", "/calls/bulk_call/{bulk_call_id}/numbers", "List rotation pool"),
            ep("Bulk Calls", "POST", "/calls/bulk_call/{bulk_call_id}/numbers", "Add number to rotation pool", {"phone_number_id": 178}),
            ep(
                "Bulk Calls",
                "PUT",
                "/calls/bulk_call/{bulk_call_id}/numbers/{assignment_id}",
                "Pause or resume pool number",
                {"is_active": False},
            ),
            ep(
                "Bulk Calls",
                "POST",
                "/calls/bulk_call/{campaign_id}/add_contacts",
                "Add contacts in bulk",
                {
                    "contacts": [
                        {"to_number": "+15551234567", "custom_variables": {"contact_name": "Ravi"}},
                        {"to_number": "+15559876543", "custom_variables": {"contact_name": "Priya"}},
                    ]
                },
            ),
            ep("Bulk Calls", "POST", "/calls/bulk_call/{bulk_call_id}/start", "Start a draft campaign", {}, danger=True),
            ep("Bulk Calls", "PUT", "/calls/bulk_call/{bulk_call_id}/concurrency", "Change concurrency", {"concurrent_call_limit": 5}),
            ep(
                "Bulk Calls",
                "POST",
                "/calls/bulk_call/{bulk_call_id}/manual_retry",
                "Retry contacts that did not connect",
                {"line_ids": [156], "retry_after_minutes": 15},
                danger=True,
            ),
            ep(
                "Bulk Calls",
                "PUT",
                "/calls/bulk_call/{bulk_call_id}/daily-time-control",
                "Set calling hours",
                {
                    "enable_daily_auto_start": True,
                    "daily_start_time": "09:00",
                    "daily_start_timezone": "America/New_York",
                    "enable_daily_hard_stop": True,
                    "daily_stop_time": "17:00",
                    "daily_stop_timezone": "America/New_York",
                },
            ),
            ep("Bulk Calls", "GET", "/bulk-call/{bulk_call_id}/live-status", "Bulk call live status"),
        ],
    },
    {
        "name": "Knowledge Base",
        "description": "Upload PDF knowledge files and attach them to agents.",
        "endpoints": [
            ep("Knowledge Base", "GET", "/knowledge_base/list", "List knowledge base files"),
            ep("Knowledge Base", "POST", "/knowledge_base/can_upload", "Check file upload capability", {"file_size": 1048576, "file_type": "application/pdf"}),
            ep(
                "Knowledge Base",
                "POST",
                "/knowledge_base/create",
                "Upload file to knowledge base",
                {"file": "BASE64_PDF_CONTENT", "filename": "sample.pdf"},
                note="Use the file helper in the UI to load a PDF into the JSON body.",
            ),
            ep(
                "Knowledge Base",
                "POST",
                "/knowledge_base/attach",
                "Attach files to agent",
                {"file_ids": [123, 456], "agent_id": 789, "access_description": "Use these files when answering policy questions."},
            ),
            ep("Knowledge Base", "POST", "/knowledge_base/detach", "Detach files from agent", {"file_ids": [123, 456], "agent_id": 789}),
            ep("Knowledge Base", "POST", "/knowledge_base/delete", "Delete file from knowledge base", {"file_id": 123}, danger=True),
        ],
    },
    {
        "name": "Phone Numbers",
        "description": "List, buy, import, attach, and release calling numbers.",
        "endpoints": [
            ep("Phone Numbers", "GET", "/phone_number/list", "List phone numbers", query={"pageno": 1, "pagesize": 30}),
            ep("Phone Numbers", "GET", "/phone_number/search", "Search available phone numbers", query={"region": "US", "carrier": "carrier-1", "pattern": "", "page": 1, "limit": 20}),
            ep(
                "Phone Numbers",
                "POST",
                "/phone_number/purchase",
                "Purchase a phone number",
                {"phone_number": "+15551234567", "region": "US", "carrier": "carrier-1"},
                danger=True,
            ),
            ep("Phone Numbers", "POST", "/phone_number/release", "Release a phone number", {"phone_number_id": 213}, danger=True),
            ep("Phone Numbers", "POST", "/phone_number/attach", "Attach phone number to agent", {"phone_number_id": 213, "agent_id": 158910}),
            ep("Phone Numbers", "POST", "/phone_number/detach", "Detach phone number", {"phone_number_id": 213}),
            ep(
                "Phone Numbers",
                "POST",
                "/phone_number/import/twilio",
                "Import Twilio number",
                {"phone_number": "+15551234567", "account_sid": "ACxxxxxxxx", "auth_token": "twilio_auth_token"},
            ),
            ep(
                "Phone Numbers",
                "POST",
                "/phone_number/import/exotel",
                "Import Exotel number",
                {
                    "phone_number": "+911234567890",
                    "subdomain": "your-subdomain",
                    "account_sid": "exotel_account_sid",
                    "api_key": "exotel_api_key",
                    "api_token": "exotel_api_token",
                },
            ),
            ep(
                "Phone Numbers",
                "POST",
                "/phone_number/import/sip",
                "Import SIP trunk",
                {
                    "phone_number": "+15551234567",
                    "sip_host": "sip.example.com",
                    "sip_port": 5060,
                    "sip_username": "username",
                    "sip_password": "password",
                    "sip_trunk_name": "Main trunk",
                },
            ),
        ],
    },
    {
        "name": "Providers",
        "description": "Discover available LLM, speech-to-text, text-to-speech, and voice options.",
        "endpoints": [
            ep("Providers", "GET", "/providers/llms", "List LLM providers"),
            ep("Providers", "GET", "/providers/voices", "List voices", query={"provider": "", "language": ""}),
            ep("Providers", "GET", "/providers/stt", "List STT providers"),
            ep("Providers", "GET", "/providers/tts", "List TTS providers"),
            ep("Providers", "GET", "/providers/all", "List all providers"),
            ep("Providers", "GET", "/providers/voice/{voice_id}", "Get voice details"),
        ],
    },
    {
        "name": "Simulation",
        "description": "Create and run tests against agents before live calling.",
        "endpoints": [
            ep("Simulation", "GET", "/simulations", "List simulations", query={"page": 1, "page_size": 30}),
            ep(
                "Simulation",
                "POST",
                "/simulations",
                "Create simulation",
                {
                    "name": "Customer Support Test",
                    "agent_id": 158910,
                    "number_of_call_to_make": 1,
                    "concurrent_call_count": 1,
                    "max_call_duration_in_minutes": 3,
                    "scenarios": [
                        {
                            "name": "Polite cancellation",
                            "description": "Ask to cancel a subscription, but be friendly.",
                            "expected_result": "Agent acknowledges the request and routes to retention.",
                            "selected_voices": [{"id": "voice_id_1", "provider": "eleven_labs"}],
                        }
                    ],
                },
            ),
            ep("Simulation", "GET", "/simulations/{simulation_id}", "Get simulation"),
            ep(
                "Simulation",
                "PUT",
                "/simulations/{simulation_id}",
                "Update simulation",
                {"name": "Updated Support Test", "number_of_call_to_make": 1, "concurrent_call_count": 1},
            ),
            ep("Simulation", "DELETE", "/simulations/{simulation_id}", "Delete simulation", danger=True),
            ep("Simulation", "POST", "/simulations/{simulation_id}/start", "Start simulation", {}, danger=True),
            ep("Simulation", "POST", "/simulations/{simulation_id}/stop", "Stop simulation", {}),
            ep("Simulation", "POST", "/simulations/{simulation_id}/enhance-prompt", "Enhance prompt", {"prompt": "Make this test more realistic."}),
        ],
    },
    {
        "name": "Reseller/Admin",
        "description": "Manage child organizations, credits, concurrency, and KYC flows.",
        "endpoints": [
            ep("Reseller/Admin", "GET", "/reseller/organizations", "List child organizations", query={"page": 1, "page_size": 30}),
            ep(
                "Reseller/Admin",
                "POST",
                "/reseller/users/add",
                "Add user",
                {"name": "Demo User", "email": "demo@example.com", "password": "temporary-password"},
            ),
            ep("Reseller/Admin", "POST", "/reseller/users/access-control", "Update user access control", {"user_id": 1234, "access": {"is_bots_menu_access": True}}),
            ep("Reseller/Admin", "POST", "/reseller/users/expiry", "Update user expiry", {"user_id": 1234, "expiry_date": "2026-12-31"}),
            ep("Reseller/Admin", "POST", "/reseller/concurrency", "Set child concurrency limit", {"user_id": 1234, "concurrent_call_limit": 3}),
            ep("Reseller/Admin", "POST", "/reseller/credits/calculate", "Calculate credit operation", {"user_id": 1234, "credits": 100}),
            ep("Reseller/Admin", "POST", "/reseller/credits/transfer", "Transfer credits to a child", {"user_id": 1234, "credits": 100}, danger=True),
            ep("Reseller/Admin", "POST", "/reseller/credits/revert", "Revert credits", {"user_id": 1234, "credits": 50}, danger=True),
            ep("Reseller/Admin", "GET", "/reseller/credits/logs", "Credit transfer logs", query={"page": 1, "page_size": 30}),
            ep("Reseller/Admin", "GET", "/reseller/kyc/status", "Get KYC status", query={"user_id": 1234}),
            ep("Reseller/Admin", "GET", "/reseller/kyc/requirements", "Get KYC requirements for a region", query={"region": "US", "carrier": "carrier-1"}),
            ep(
                "Reseller/Admin",
                "POST",
                "/reseller/kyc/steps/{step}",
                "Submit a KYC verification step",
                {"user_id": 1234, "region": "US", "carrier": "carrier-1", "name": "Demo User", "email": "demo@example.com", "phone": "+15551234567"},
            ),
        ],
    },
]


ENDPOINTS = [endpoint for group in GROUPS for endpoint in group["endpoints"]]


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compact_json(value):
    text = json.dumps(value, ensure_ascii=True, separators=(",", ":")) if not isinstance(value, str) else value
    if len(text) > MAX_LOG_CHARS:
        return text[:MAX_LOG_CHARS] + "\n... truncated ..."
    return text


def get_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS request_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint_id TEXT,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                url TEXT NOT NULL,
                status INTEGER,
                ok INTEGER NOT NULL,
                duration_ms INTEGER NOT NULL,
                request_json TEXT,
                response_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS saved_payloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint_id TEXT NOT NULL,
                name TEXT NOT NULL,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                query_json TEXT NOT NULL,
                body_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("base_url", DEFAULT_BASE_URL, now_iso()),
        )


def read_settings(include_secret=False):
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    raw = {row["key"]: row["value"] for row in rows}
    api_key = raw.get("api_key", "")
    data = {
        "baseUrl": raw.get("base_url", DEFAULT_BASE_URL),
        "hasApiKey": bool(api_key),
        "apiKeyPreview": f"...{api_key[-4:]}" if api_key else "",
    }
    if include_secret:
        data["apiKey"] = api_key
    return data


def save_setting(key, value):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now_iso()),
        )


def delete_setting(key):
    with get_db() as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))


def build_url(base_url, path, query):
    base = base_url.rstrip("/")
    parsed_pairs = []
    for key, value in (query or {}).items():
        if value is None or value == "":
            continue
        if isinstance(value, list):
            for item in value:
                if item is not None and item != "":
                    parsed_pairs.append((key, item))
        else:
            parsed_pairs.append((key, value))
    suffix = urllib.parse.urlencode(parsed_pairs, doseq=True)
    return f"{base}{path}" + (f"?{suffix}" if suffix else "")


def parse_json_bytes(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc


def log_history(endpoint_id_value, method, path, url, status, ok, duration_ms, request_payload, response_payload):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO request_history
            (endpoint_id, method, path, url, status, ok, duration_ms, request_json, response_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                endpoint_id_value,
                method,
                path,
                url,
                status,
                1 if ok else 0,
                duration_ms,
                compact_json(request_payload),
                compact_json(response_payload),
                now_iso(),
            ),
        )


class AppHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        self.route()

    def do_POST(self):
        self.route()

    def do_PUT(self):
        self.route()

    def do_PATCH(self):
        self.route()

    def do_DELETE(self):
        self.route()

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")

    def route(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path.startswith("/api/"):
                self.route_api(path, parsed)
                return
            self.serve_static(path)
        except ValueError as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:  # noqa: BLE001
            self.send_json({"ok": False, "error": "Server error", "detail": str(exc)}, status=500)

    def route_api(self, path, parsed):
        if path == "/api/health" and self.command == "GET":
            self.send_json({"ok": True, "time": now_iso(), "database": str(DB_PATH), "endpointCount": len(ENDPOINTS)})
            return

        if path == "/api/endpoints" and self.command == "GET":
            self.send_json({"groups": GROUPS, "endpoints": ENDPOINTS})
            return

        if path == "/api/settings":
            if self.command == "GET":
                self.send_json(read_settings())
                return
            if self.command in {"POST", "PUT"}:
                data = self.read_json()
                base_url = data.get("baseUrl", "").strip()
                api_key = data.get("apiKey", "").strip()
                if base_url:
                    if not base_url.startswith("https://"):
                        raise ValueError("Base URL must start with https://")
                    save_setting("base_url", base_url.rstrip("/"))
                if api_key:
                    save_setting("api_key", api_key)
                self.send_json(read_settings())
                return

        if path == "/api/settings/api-key" and self.command == "DELETE":
            delete_setting("api_key")
            self.send_json(read_settings())
            return

        if path == "/api/history":
            if self.command == "GET":
                query = urllib.parse.parse_qs(parsed.query)
                limit = int(query.get("limit", ["80"])[0])
                limit = max(1, min(limit, 250))
                with get_db() as conn:
                    rows = conn.execute(
                        """
                        SELECT * FROM request_history
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()
                self.send_json({"records": [dict(row) for row in rows]})
                return
            if self.command == "DELETE":
                with get_db() as conn:
                    conn.execute("DELETE FROM request_history")
                self.send_json({"ok": True})
                return

        if path == "/api/saved-payloads":
            if self.command == "GET":
                query = urllib.parse.parse_qs(parsed.query)
                endpoint_filter = query.get("endpoint_id", [""])[0]
                with get_db() as conn:
                    if endpoint_filter:
                        rows = conn.execute(
                            "SELECT * FROM saved_payloads WHERE endpoint_id = ? ORDER BY updated_at DESC",
                            (endpoint_filter,),
                        ).fetchall()
                    else:
                        rows = conn.execute("SELECT * FROM saved_payloads ORDER BY updated_at DESC").fetchall()
                self.send_json({"records": [dict(row) for row in rows]})
                return
            if self.command == "POST":
                data = self.read_json()
                required = ["endpoint_id", "name", "method", "path"]
                missing = [key for key in required if not data.get(key)]
                if missing:
                    raise ValueError(f"Missing fields: {', '.join(missing)}")
                ts = now_iso()
                with get_db() as conn:
                    cur = conn.execute(
                        """
                        INSERT INTO saved_payloads
                        (endpoint_id, name, method, path, query_json, body_json, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            data["endpoint_id"],
                            data["name"],
                            data["method"],
                            data["path"],
                            compact_json(data.get("query", {})),
                            compact_json(data.get("body", {})),
                            ts,
                            ts,
                        ),
                    )
                self.send_json({"ok": True, "id": cur.lastrowid})
                return

        saved_match = re.fullmatch(r"/api/saved-payloads/(\d+)", path)
        if saved_match and self.command == "DELETE":
            with get_db() as conn:
                conn.execute("DELETE FROM saved_payloads WHERE id = ?", (int(saved_match.group(1)),))
            self.send_json({"ok": True})
            return

        if path == "/api/run" and self.command == "POST":
            self.run_omni_request()
            return

        self.send_json({"ok": False, "error": "Not found"}, status=404)

    def run_omni_request(self):
        data = self.read_json()
        method = data.get("method", "GET").upper()
        path = data.get("path", "")
        query = data.get("query") or {}
        body = data.get("body", None)
        endpoint_id_value = data.get("endpointId", endpoint_id(method, path))

        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("Unsupported HTTP method")
        if not isinstance(path, str) or not path.startswith("/"):
            raise ValueError("Path must start with /")
        if "://" in path:
            raise ValueError("Path must be relative to the OmniDimension API base URL")
        if not isinstance(query, dict):
            raise ValueError("Query must be a JSON object")

        settings = read_settings(include_secret=True)
        api_key = settings.get("apiKey", "")
        if not api_key:
            self.send_json({"ok": False, "error": "Save your OmniDimension API key before sending requests."}, status=400)
            return

        url = build_url(settings["baseUrl"], path, query)
        started = time.perf_counter()
        request_payload = {"method": method, "path": path, "query": query, "body": body}
        status = None
        ok = False
        response_payload = None

        try:
            payload_bytes = None
            headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
            if method != "GET" and body is not None:
                payload_bytes = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"

            request = urllib.request.Request(url, data=payload_bytes, headers=headers, method=method)
            with urllib.request.urlopen(request, timeout=60) as response:
                status = response.status
                raw = response.read()
                response_payload = self.decode_response(raw, response.headers.get_content_charset())
                ok = 200 <= status < 300
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read()
            response_payload = self.decode_response(raw, exc.headers.get_content_charset())
            ok = False
        except urllib.error.URLError as exc:
            response_payload = {"error": "Network error", "detail": str(exc.reason)}
            ok = False
        except TimeoutError:
            response_payload = {"error": "Timeout", "detail": "The OmniDimension API request took too long."}
            ok = False

        duration_ms = int((time.perf_counter() - started) * 1000)
        log_history(endpoint_id_value, method, path, url, status, ok, duration_ms, request_payload, response_payload)
        self.send_json(
            {
                "ok": ok,
                "status": status,
                "durationMs": duration_ms,
                "url": url,
                "data": response_payload,
            },
            status=200 if status is None or status < 500 else 502,
        )

    def decode_response(self, raw, charset):
        if not raw:
            return None
        text = raw.decode(charset or "utf-8", errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return parse_json_bytes(self.rfile.read(length))

    def serve_static(self, path):
        if path in {"", "/"}:
            file_path = STATIC_DIR / "index.html"
        else:
            requested = path.lstrip("/")
            if requested.startswith("static/"):
                requested = requested[len("static/") :]
            file_path = (STATIC_DIR / requested).resolve()
            if not str(file_path).startswith(str(STATIC_DIR.resolve())):
                self.send_error(403)
                return
            if not file_path.exists() or not file_path.is_file():
                file_path = STATIC_DIR / "index.html"

        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, value, status=200):
        data = json.dumps(value, ensure_ascii=True, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def main():
    parser = argparse.ArgumentParser(description="OmniDimension Control Center")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    init_db()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"OmniDimension Control Center running at http://{args.host}:{args.port}")
    print(f"Database: {DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
