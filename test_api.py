# tests/test_api.py
import os
import re
import time
import uuid
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
import httpx
import pytest

"""
User Management API

Notes:
- Set BASE_URL to point at a running server (default: http://127.0.0.1:8000).
- seed_data.py is optional; the suite can create its own users when needed.
- Rate limiting in this API is per-client-IP for /users (create). To keep the suite stable
  in reviewer environments, request helpers attach a TEST-NET client IP by default unless you
  explicitly set X-Real-IP / X-Forwarded-For.
- To intentionally omit optional fields from a request body (vs sending null), helpers accept
  the _OMIT sentinel.
- Heavier checks are tagged:
    - @pytest.mark.security  (rate-limit / brute-force / timing signals)
    - @pytest.mark.perf      (performance / concurrency)

Tip:
- Execution order is annotated via @pytest.mark.order(N) to tell a coherent story.
  If pytest-order (pytest-order/pytest-ordering) isn't installed, tests still run;
  only ordering won't be enforced.

pytest.ini:
- A pytest.ini file is included in this project to formally register custom markers:
    - order
    - security
    - perf
  It prevents PytestUnknownMarkWarning warnings and enables clean marker-based filtering.

Handy runs:
    pytest -q
    pytest -m "not security and not perf"
    pytest -m security
    pytest -m perf
"""

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")

# Soft, configurable performance targets (ms)
PERF_THRESHOLD_MS = float(os.getenv("PERF_THRESHOLD_MS", "300"))
PERF_PAGINATION_THRESHOLD_MS = float(os.getenv("PERF_PAGINATION_THRESHOLD_MS", "900"))

# Timing-enum sentinel threshold (ms). Keep conservative to reduce false positives.
TIMING_ENUM_THRESHOLD_MS = float(os.getenv("TIMING_ENUM_THRESHOLD_MS", "60"))

# Seeded accounts (present only if seed_data.py was executed)
SEEDED = [
    ("john_doe", "password123"),
    ("jane_smith", "securepass456"),
    ("admin_user", "Admin@2024"),
    ("test_user", "Test@123"),
]

# -----------------------------------------------------------------------------
# Execution order
# -----------------------------------------------------------------------------
#  1-2    Smoke: / + /health
#  3-15   /users (POST): create + validation + edge cases + overwrite sentinel
#  16-22  /users (GET): read/list + pagination/sorting + schema checks
#  23-26  /users/search: query params + exact/partial behavior
#  27-32  /login + /logout: token format + invalid creds + logout behavior
#  33-40  /users/{id} (PUT): authz/session hardening + validation + xfail signals
#  41-46  /users/{id} (DELETE): delete auth + immutability + data integrity checks
#  47-49  /stats + /users/bulk: disclosure checks + hidden endpoint behavior
#  50-56  Input hardening: XSS/null bytes/SQLi-ish strings + header quirks
#  57-60  Performance & concurrency (marked with @perf)
#  61-63  Security signals (marked with @security)
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------
def unique_user(prefix: str = "qa"):
    u = f"{prefix}_{uuid.uuid4().hex[:8]}"
    return u, f"{u}@example.com"


def bearer(token: str):
    return {"Authorization": f"Bearer {token}"}


def basic(user: str, pwd: str):
    return (user, pwd)


# Sentinel used when we want to omit an optional field from the request body.
_OMIT = object()


def _with_default_client_ip(headers=None):
    """
    Helper to keep the suite stable against the simplistic per-IP rate limiter.

    If the caller didn't explicitly set a client IP header, we attach a TEST-NET IP
    (RFC 5737) so that large create-heavy suites don't accidentally trip 429s.
    """
    h = dict(headers or {})
    lower_keys = {k.lower() for k in h.keys()}
    if "x-real-ip" not in lower_keys and "x-forwarded-for" not in lower_keys:
        octet = int(uuid.uuid4().hex[:2], 16) % 254 + 1
        h["x-real-ip"] = f"198.51.100.{octet}"
    return h


def _extract_token(resp: httpx.Response):
    """Resilient token extraction (keeps helper reusable across environments)."""
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    if isinstance(data, dict):
        tok = data.get("token")
        return tok if isinstance(tok, str) and tok else None
    return None


def login(username, password, headers=None):
    return httpx.post(
        f"{BASE_URL}/login",
        json={"username": username, "password": password},
        headers=headers or {},
        timeout=10,
    )


def logout(token=None, headers=None):
    if token:
        return httpx.post(f"{BASE_URL}/logout", headers=bearer(token), timeout=10)
    return httpx.post(f"{BASE_URL}/logout", headers=headers or {}, timeout=10)


def create_user(
    username,
    email,
    password="Abc12345!",
    age=25,
    phone="+15551234567",
    headers=None,
):
    payload = {"username": username, "email": email, "password": password, "age": age}
    # phone is optional; some tests intentionally omit it from the request body
    if phone is not _OMIT:
        payload["phone"] = phone
    return httpx.post(
        f"{BASE_URL}/users",
        json=payload,
        headers=_with_default_client_ip(headers),
        timeout=10,
    )


def list_users(limit=10, offset=0, **kwargs):
    params = {"limit": limit, "offset": offset}
    params.update(kwargs)
    return httpx.get(f"{BASE_URL}/users", params=params, timeout=10)


def get_user(user_id):
    return httpx.get(f"{BASE_URL}/users/{user_id}", timeout=10)


def update_user(user_id, token, payload, extra_headers=None):
    h = bearer(token)
    if extra_headers:
        h.update(extra_headers)
    return httpx.put(f"{BASE_URL}/users/{user_id}", headers=h, json=payload, timeout=10)


def delete_user(user_id, auth=None, headers=None):
    return httpx.delete(
        f"{BASE_URL}/users/{user_id}",
        auth=auth,
        headers=_with_default_client_ip(headers),
        timeout=10,
    )


def search_users(q, field="all", exact=False):
    return httpx.get(
        f"{BASE_URL}/users/search",
        params={"q": q, "field": field, "exact": exact},
        timeout=10,
    )


def stats(include_details=False):
    return httpx.get(f"{BASE_URL}/stats", params={"include_details": include_details}, timeout=10)


def bulk_create(users_payload):
    return httpx.post(f"{BASE_URL}/users/bulk", json=users_payload, timeout=10)


def _login_seed_or_create_fallback():
    """
    Prefer seeded login; if seeds aren't available, create a new user and login.
    Keeps the suite runnable in reviewer environments.
    """
    for u, p in SEEDED:
        r = login(u, p)
        tok = _extract_token(r)
        if tok:
            return u, tok

    uname, email = unique_user("fallback")
    cr = create_user(uname, email, password="Abc12345!")
    if cr.status_code == 201:
        lr = login(uname, "Abc12345!")
        tok = _extract_token(lr)
        if tok:
            return uname, tok

    return None, None


def _create_deleter_account():
    """
    DELETE uses HTTP Basic auth (verify_credentials).
    Since seeding is optional, we always create a dedicated user for Basic-auth tests.
    """
    uname, email = unique_user("deleter")
    pw = "Abc12345!"
    cr = create_user(uname, email, password=pw, age=30, phone="+15550001111")
    assert cr.status_code == 201, f"Could not create deleter account (status={cr.status_code}): {cr.text}"
    return uname.lower(), pw  # API stores lowercase username


# -----------------------------------------------------------------------------
# Schema checks (light, pragmatic)
# -----------------------------------------------------------------------------
def assert_user_schema(obj):
    assert isinstance(obj, dict)
    for k in ("id", "username", "email", "age", "created_at", "is_active"):
        assert k in obj, f"Missing key '{k}'"

    assert isinstance(obj["id"], int)
    assert isinstance(obj["username"], str)
    assert isinstance(obj["email"], str)
    assert isinstance(obj["age"], int)
    assert isinstance(obj["created_at"], str)  # datetime serialized to ISO string
    assert isinstance(obj["is_active"], bool)

    # optional keys
    if "phone" in obj:
        assert obj["phone"] is None or isinstance(obj["phone"], str)
    if "last_login" in obj:
        assert obj["last_login"] is None or isinstance(obj["last_login"], str)


def assert_users_list_schema(arr):
    assert isinstance(arr, list)
    for it in arr:
        assert_user_schema(it)


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------
class TestSmoke:
    # Suite: Smoke

    @pytest.mark.order(1)
    def test_root(self):
        # Smoke check for the API root payload.
        r = httpx.get(f"{BASE_URL}/", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body.get("message") == "User Management API"
        assert body.get("version") == "1.0.0"

    @pytest.mark.order(2)
    def test_health(self):
        h = httpx.get(f"{BASE_URL}/health", timeout=10)
        assert h.status_code == 200
        body = h.json()
        assert body.get("status") == "healthy"
        assert "timestamp" in body and isinstance(body["timestamp"], str)

        # API returns int() of len(str(dict)) -> still int, keep sanity checks
        assert "memory_users" in body and isinstance(body["memory_users"], int)
        assert "memory_sessions" in body and isinstance(body["memory_sessions"], int)
        assert body["memory_users"] >= 0
        assert body["memory_sessions"] >= 0



class TestUsersCreate:
    # Suite: Users — Create

    @pytest.mark.order(3)
    def test_create_user_success_and_get_by_id(self):
        uname, email = unique_user("ok")
        r = create_user(uname, email)
        assert r.status_code == 201
        user = r.json()
        assert_user_schema(user)

        # API lowercases username in storage/response
        assert user["username"] == uname.lower()

        # Never return password/hash in response body (simple leakage check)
        lower = r.text.lower()
        assert "password" not in lower and "hash" not in lower

        uid = user["id"]
        g = get_user(uid)
        assert g.status_code == 200
        got = g.json()
        assert_user_schema(got)
        assert got["id"] == uid
        assert got["username"] == uname.lower()

    @pytest.mark.order(4)
    def test_duplicate_username(self):
        # Creating the same username twice should be rejected.
        u, e = unique_user("dup")
        r1 = create_user(u, e)
        assert r1.status_code == 201

        r2 = create_user(u, f"{u}@alt.com")
        assert r2.status_code == 400
        assert "username already exists" in r2.text.lower()

    @pytest.mark.order(5)
    def test_invalid_age_under_min(self):
        # Validate lower age boundary (18+).
        uname, email = unique_user("underage")
        r = create_user(uname, email, age=17)
        assert r.status_code in (400, 422)

    @pytest.mark.order(6)
    def test_invalid_age_over_max(self):
        # Validate upper age boundary (<=150).
        uname, email = unique_user("overage")
        r = create_user(uname, email, age=151)
        assert r.status_code in (400, 422)

    @pytest.mark.order(7)
    def test_invalid_email_rejected(self):
        # Email format validation should fail with 422.
        uname, _ = unique_user("badmail")
        r = create_user(uname, "not-an-email")
        assert r.status_code in (400, 422)

    @pytest.mark.order(8)
    def test_short_password_rejected(self):
        # Password min length validation.
        uname, email = unique_user("shortpw")
        r = create_user(uname, email, password="12345")  # min_length=6
        assert r.status_code in (400, 422)

    @pytest.mark.order(9)
    def test_create_user_invalid_phone_matrix(self):
        invalid_phones = [
            "abc",
            "++15551234567",
            "+1(555)123-4567",
            "123 456 7890",
            "123-456-7890",
            "phone123",
        ]
        for i, ph in enumerate(invalid_phones):
            uname, email = unique_user(f"invph{i}")
            resp = create_user(uname, email, phone=ph)
            assert resp.status_code in (400, 422)
            # validator message appears in 422 response JSON; string match kept loose
            assert "invalid phone number format" in resp.text.lower()


    @pytest.mark.order(10)
    def test_create_user_without_phone_success(self):
        # Phone is optional; request should succeed when omitted.
        uname, email = unique_user("nophone")
        r = create_user(uname, email, phone=_OMIT)
        assert r.status_code == 201
        body = r.json()
        assert_user_schema(body)
        assert body.get("phone") is None


    @pytest.mark.order(11)
    def test_username_length_boundaries(self):
        # min_length=3 / max_length=50
        u_min = f"min{uuid.uuid4().hex[:6]}"
        r1 = create_user(u_min, f"{u_min}@example.com")
        assert r1.status_code == 201

        u_max = ("u" * 46) + "_" + uuid.uuid4().hex[:3]  # 46 + 1 + 3 = 50 chars
        assert len(u_max) == 50
        r2 = create_user(u_max, f"{uuid.uuid4().hex[:8]}@example.com")
        assert r2.status_code == 201

        u_too_long = "u" * 51
        r3 = create_user(u_too_long, f"{uuid.uuid4().hex[:8]}@example.com")
        assert r3.status_code in (400, 422)

    @pytest.mark.order(12)
    def test_username_invalid_characters_rejected(self):
        # spaces are not allowed by regex
        uname = "bad name"
        r = create_user(uname, f"{uuid.uuid4().hex[:6]}@example.com")
        assert r.status_code in (400, 422)
        assert "invalid characters" in r.text.lower()

    @pytest.mark.order(13)
    def test_unicode_characters_in_username_rejected(self):
        # regex allows only a-zA-Z0-9 _ - ' " ;
        uname = f"用户_{uuid.uuid4().hex[:4]}"
        r = create_user(uname, f"{uuid.uuid4().hex[:6]}@example.com")
        assert r.status_code in (400, 422)
        assert "invalid characters" in r.text.lower()

    @pytest.mark.order(14)
    def test_username_allows_quotes_semicolon_by_contract(self):
        """
        Contract/positive test:
        API explicitly allows characters: ' " ; - _ along with alnum.
        """
        uname = f"ok_user'{uuid.uuid4().hex[:4]};"
        email = f"{uuid.uuid4().hex[:8]}@example.com"
        r = create_user(uname, email)
        assert r.status_code == 201
        assert r.json()["username"] == uname.lower()

    @pytest.mark.order(15)
    def test_case_collision_overwrite_sentinel_xfail(self):
        """
        BUG-001 sentinel:
        create_user checks existence using original casing (user.username),
        but stores by lowercased key. Creating 'Name' then 'NAME' can overwrite
        or make the first record unreachable by id.
        """
        base, mail = unique_user("caseow")
        c1 = create_user(base, mail)
        assert c1.status_code == 201
        id1 = c1.json()["id"]

        c2 = create_user(base.upper(), f"{base}@alt.com")
        assert c2.status_code in (201, 400)

        if c2.status_code == 201:
            g = get_user(id1)
            if g.status_code == 404:
                pytest.xfail("BUG-001: Case-collision overwrite detected (original record vanished).")



class TestUsersReadList:
    # Suite: Users — Read & List

    @pytest.mark.order(16)
    def test_list_users_schema(self):
        # List endpoint returns an array of UserResponse objects.
        r = list_users(limit=10, offset=0)
        assert r.status_code == 200
        assert_users_list_schema(r.json())

    @pytest.mark.order(17)
    def test_get_user_invalid_id_format(self):
        # Non-numeric user_id should return a 400 with a clear message.
        r = get_user("not_a_number")
        assert r.status_code == 400
        assert "invalid user id format" in r.text.lower()

    @pytest.mark.order(18)
    def test_get_user_not_found(self):
        # Unknown numeric id should return 404.
        r = get_user(999999)
        assert r.status_code == 404
        assert "user not found" in r.text.lower()

    @pytest.mark.order(19)
    def test_pagination_limit_off_by_one_sentinel_xfail(self):
        """
        BUG-002 sentinel:
        list_users slices [offset : offset + limit + 1] → can return more than requested.
        """
        for _ in range(8):
            u, e = unique_user("limit")
            create_user(u, e)

        limit = 5
        r = list_users(limit=limit, offset=0)
        assert r.status_code == 200
        arr = r.json()
        assert_users_list_schema(arr)

        if len(arr) > limit:
            pytest.xfail(f"BUG-002: /users returned {len(arr)} items for limit={limit} (off-by-one).")

    @pytest.mark.order(20)
    def test_sorting_supported_fields(self):
        # Sort parameters should work for allowed fields.
        r = list_users(limit=10, offset=0, sort_by="id", order="asc")
        assert r.status_code == 200
        assert_users_list_schema(r.json())

        r2 = list_users(limit=10, offset=0, sort_by="username", order="desc")
        assert r2.status_code == 200
        assert_users_list_schema(r2.json())

        r3 = list_users(limit=10, offset=0, sort_by="created_at", order="asc")
        assert r3.status_code == 200
        assert_users_list_schema(r3.json())

    @pytest.mark.order(21)
    def test_sorting_created_at_string_sort_quality_signal(self):
        """
        BUG-023 sentinel (conditional):
        API sorts created_at via str(datetime). ISO-ish strings often sort, but not always.
        If order is clearly not monotonic -> xfail signal.
        """
        for _ in range(3):
            u, e = unique_user("ctime")
            create_user(u, e)

        r = list_users(limit=20, offset=0, sort_by="created_at", order="asc")
        assert r.status_code == 200
        arr = r.json()
        created = [it["created_at"] for it in arr]
        if created != sorted(created):
            pytest.xfail("BUG-023: created_at sorting is not monotonic (string-based sort issue).")

    @pytest.mark.parametrize(
        "params",
        [
            {"limit": 101, "offset": 0},                 # limit > 100
            {"limit": 10, "offset": -1},                 # offset < 0
            {"limit": 10, "offset": 0, "order": "x"},    # invalid order
            {"limit": 10, "offset": 0, "sort_by": "x"},  # invalid sort_by (regex)
        ],
    )
    @pytest.mark.order(22)
    def test_list_users_invalid_query_params_rejected(self, params):
        # Invalid query params should be rejected by FastAPI validation.
        r = httpx.get(f"{BASE_URL}/users", params=params, timeout=10)
        assert r.status_code in (400, 422)


class TestUsersSearch:
    # Suite: Users — Search (/users/search)

    @pytest.mark.order(23)
    def test_search_partial_and_exact(self):
        # Search should support partial matching and exact username matching.
        uname, email = unique_user("searchMe")
        cr = create_user(uname, email)
        assert cr.status_code == 201

        r = search_users(uname[:5], field="all", exact=False)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

        r2 = search_users(uname.lower(), field="username", exact=True)
        assert r2.status_code == 200
        assert any(it.get("username") == uname.lower() for it in r2.json())

    @pytest.mark.order(24)
    def test_search_email_exact_flag_behavior_sentinel_xfail(self):
        """
        BUG-007 sentinel:
        /users/search uses substring match for email even when exact=true.
        """
        uname, _ = unique_user("exactMail")
        email = f"exactmail_{uuid.uuid4().hex[:6]}@example.com"
        cr = create_user(uname, email)
        assert cr.status_code == 201

        r = search_users("exactmail_", field="email", exact=True)
        assert r.status_code == 200
        arr = r.json()
        if arr:
            pytest.xfail("BUG-007: Email search returns substring matches even with exact=true (should be exact match).")

    @pytest.mark.order(25)
    def test_search_invalid_field_rejected(self):
        # Invalid field option should be rejected (422).
        r = search_users("john", field="id", exact=False)
        assert r.status_code in (400, 422)

    @pytest.mark.order(26)
    def test_unicode_security_search_query(self):
        # Search should safely handle non-ASCII input.
        r = search_users("şüğİ漢字", field="all", exact=False)
        assert r.status_code == 200
        assert isinstance(r.json(), list)



class TestAuth:
    # Suite: Authentication

    @pytest.mark.order(27)
    def test_login_success_token_format_and_uniqueness(self):
        """
        Token quality checks based on implementation:
        - token is sha256(...)[:32] => 32 hex chars
        - two logins should typically produce different tokens (timestamp included)
        """
        user, token1 = _login_seed_or_create_fallback()
        assert token1 is not None
        assert re.fullmatch(r"[0-9a-f]{32}", token1) is not None

        # second login: should issue a new token
        if user is None:
            pytest.skip("Could not obtain a user for token uniqueness check.")
        pwd = next((p for u, p in SEEDED if u == user), "Abc12345!")
        r2 = login(user, pwd)
        token2 = _extract_token(r2)
        assert token2 is not None
        assert re.fullmatch(r"[0-9a-f]{32}", token2) is not None
        assert token2 != token1


    @pytest.mark.order(28)
    def test_login_username_is_case_insensitive(self):
        # Login should treat usernames case-insensitively (per implementation).
        uname, email = unique_user("caseLogin")
        pw = "Abc12345!"
        cr = create_user(uname, email, password=pw)
        assert cr.status_code == 201

        r = login(uname.upper(), pw)
        assert r.status_code == 200
        tok = _extract_token(r)
        assert tok is not None

    @pytest.mark.order(29)
    def test_login_invalid_username(self):
        # Invalid username should return 401 without leaking details.
        r = login("nonexistent_user", "password123")
        assert r.status_code == 401
        assert "invalid username or password" in r.text.lower()

    @pytest.mark.order(30)
    def test_login_invalid_password(self):
        # Wrong password should return 401.
        r = login("john_doe", "wrongpass")
        assert r.status_code == 401
        assert "invalid username or password" in r.text.lower()

    @pytest.mark.order(31)
    def test_login_empty_credentials(self):
        # Empty credentials should fail validation.
        r = login("", "")
        assert r.status_code in (401, 422)

    @pytest.mark.order(32)
    def test_logout_current_behavior_documented(self):
        """
        Current API behavior (as implemented):
        - Missing/invalid header OR wrong scheme -> 200 + "No active session"
        - Invalid Bearer token -> 200 + "Logged out successfully" (even if token not found)
        """
        r1 = logout()
        assert r1.status_code == 200
        assert r1.json().get("message") == "No active session"

        r2 = logout(headers={"Authorization": "InvalidFormat"})
        assert r2.status_code == 200
        assert r2.json().get("message") == "No active session"

        r3 = logout(headers={"Authorization": "Bearer definitely_not_real"})
        assert r3.status_code == 200
        assert r3.json().get("message") == "Logged out successfully"



class TestUsersUpdate:
    # Suite: Users — Update & Sessions

    @pytest.mark.order(33)
    def test_update_without_token_returns_401(self):
        # Update is protected; missing token should be 401.
        uname, email = unique_user("updna")
        cr = create_user(uname, email)
        assert cr.status_code == 201
        uid = cr.json()["id"]

        up = httpx.put(f"{BASE_URL}/users/{uid}", json={"email": "nobody@example.com"}, timeout=10)
        assert up.status_code == 401
        assert "authentication required" in up.text.lower()

    @pytest.mark.order(34)
    def test_update_with_invalid_token_returns_401(self):
        # Unknown token should be rejected as an invalid session.
        uname, email = unique_user("invtoken")
        cr = create_user(uname, email)
        assert cr.status_code == 201
        uid = cr.json()["id"]

        up = httpx.put(
            f"{BASE_URL}/users/{uid}",
            headers={"Authorization": "Bearer deadbeefdeadbeefdeadbeefdeadbeef"},
            json={"email": "x@example.com"},
            timeout=10,
        )
        assert up.status_code == 401
        assert "invalid session" in up.text.lower()

    @pytest.mark.order(35)
    def test_update_with_malformed_authorization_header(self):
        # Authorization header must be a Bearer token.
        uname, email = unique_user("malbearer")
        cr = create_user(uname, email)
        assert cr.status_code == 201
        uid = cr.json()["id"]

        up = httpx.put(
            f"{BASE_URL}/users/{uid}",
            headers={"Authorization": "Token abc"},
            json={"email": "x@example.com"},
            timeout=10,
        )
        assert up.status_code == 401
        assert "invalid authorization header" in up.text.lower()


    @pytest.mark.order(36)
    def test_update_invalid_email_rejected(self):
        # Update payload is validated (email).
        uname, email = unique_user("updBadMail")
        cr = create_user(uname, email)
        assert cr.status_code == 201
        uid = cr.json()["id"]

        _, token = _login_seed_or_create_fallback()
        assert token is not None

        up = update_user(uid, token, {"email": "not-an-email"})
        assert up.status_code in (400, 422)


    @pytest.mark.order(37)
    def test_update_age_under_min_rejected(self):
        # Update payload is validated (age).
        uname, email = unique_user("updBadAge")
        cr = create_user(uname, email)
        assert cr.status_code == 201
        uid = cr.json()["id"]

        _, token = _login_seed_or_create_fallback()
        assert token is not None

        up = update_user(uid, token, {"age": 17})
        assert up.status_code in (400, 422)

    @pytest.mark.security
    @pytest.mark.order(38)
    def test_authorization_bypass_attempt_foreign_update_xfail(self):
        """
        BUG-003 sentinel:
        verify_session() authenticates, but update_user() has no ownership/role check.
        If any authenticated user can update any other user -> xfail.
        """
        _, token = _login_seed_or_create_fallback()
        assert token is not None

        victim, vmail = unique_user("victim")
        cr = create_user(victim, vmail)
        assert cr.status_code == 201
        uid = cr.json()["id"]

        up = update_user(uid, token, {"email": "pwned@example.com"})
        if up.status_code == 200:
            assert_user_schema(up.json())
            pytest.xfail("BUG-003: Foreign user update allowed (authorization bypass).")
        assert up.status_code in (401, 403, 404)

    @pytest.mark.security
    @pytest.mark.order(39)
    def test_session_hijacking_attempt_token_not_ip_bound_xfail(self):
        """
        BUG-009 sentinel:
        sessions store 'ip', but verify_session() does not enforce IP binding.
        If the same token works from a different client IP context -> xfail.
        """
        uname, email = unique_user("ipbind")
        pw = "Abc12345!"
        cr = create_user(uname, email, password=pw)
        assert cr.status_code == 201

        r = login(uname, pw, headers={"x-real-ip": "203.0.113.10"})
        tok = _extract_token(r)
        assert tok is not None

        target, tmail = unique_user("hijack")
        tcr = create_user(target, tmail)
        assert tcr.status_code == 201
        uid = tcr.json()["id"]

        up = update_user(
            uid,
            tok,
            {"email": f"{target}@changed.example.com"},
            extra_headers={"x-real-ip": "198.51.100.88"},
        )

        if up.status_code == 200:
            pytest.xfail("BUG-009: Session token works across different client IP contexts (hijack risk).")

        assert up.status_code in (401, 403)

    @pytest.mark.order(40)
    def test_update_after_logout_token_invalidated(self):
        # Logout should invalidate the session token.
        _, token = _login_seed_or_create_fallback()
        assert token is not None

        lo = logout(token=token)
        assert lo.status_code == 200

        uname, email = unique_user("afterlogout")
        cr = create_user(uname, email)
        assert cr.status_code == 201
        uid = cr.json()["id"]

        up = update_user(uid, token, {"email": f"{uname}@postlogout.example.com"})
        assert up.status_code == 401
        assert "invalid session" in up.text.lower()



class TestUsersDelete:
    # Suite: Users — Delete & Data integrity

    @pytest.mark.order(41)
    def test_delete_user_without_auth(self):
        # Delete is protected with Basic auth.
        r = delete_user(1)
        assert r.status_code == 401
        msg = r.text.lower()
        assert ("invalid credentials" in msg) or ("not authenticated" in msg)

    @pytest.mark.order(42)
    def test_delete_user_invalid_credentials(self):
        # Invalid Basic credentials should be rejected.
        auth_user, auth_pass = _create_deleter_account()

        victim, vmail = unique_user("victimdel")
        cr = create_user(victim, vmail)
        assert cr.status_code == 201
        uid = cr.json()["id"]

        r = delete_user(uid, auth=basic(auth_user, f"{auth_pass}WRONG"))
        assert r.status_code == 401
        assert "invalid credentials" in r.text.lower()


    @pytest.mark.order(43)
    def test_delete_nonexistent_user_returns_404_with_valid_basic_auth(self):
        # Deleting a missing user should return 404 (even with valid auth).
        auth_user, auth_pass = _create_deleter_account()
        r = delete_user(999999, auth=basic(auth_user, auth_pass))
        assert r.status_code == 404
        assert "user not found" in r.text.lower()

    @pytest.mark.security
    @pytest.mark.order(44)
    def test_delete_user_authorization_bypass_xfail(self):
        """
        BUG-005 sentinel:
        DELETE only checks "is this a valid Basic user" — there is no ownership/role check.
        Any user can delete any other user -> xfail signal.
        """
        auth_user, auth_pass = _create_deleter_account()

        victim, vmail = unique_user("softdel")
        cr = create_user(victim, vmail)
        assert cr.status_code == 201
        uid = cr.json()["id"]

        r = delete_user(uid, auth=basic(auth_user, auth_pass))
        if r.status_code == 200:
            pytest.xfail("BUG-005: Any valid Basic user can delete any user (missing authorization).")
        assert r.status_code in (401, 403, 404)

    @pytest.mark.order(45)
    def test_soft_deleted_user_update_returns_unchanged(self):
        # Soft-deleted users should not be mutated via update.
        auth_user, auth_pass = _create_deleter_account()

        uname, email = unique_user("immut")
        cr = create_user(uname, email)
        assert cr.status_code == 201
        uid = cr.json()["id"]

        delr = delete_user(uid, auth=basic(auth_user, auth_pass))
        assert delr.status_code == 200

        _, token = _login_seed_or_create_fallback()
        assert token is not None

        up = update_user(uid, token, {"email": f"{uname}@new.example.com", "age": 40})
        assert up.status_code == 200
        user = up.json()
        assert_user_schema(user)
        assert user["is_active"] is False
        assert user["email"] == email
        assert user["age"] == 25

    @pytest.mark.order(46)
    def test_duplicate_phone_rejected_or_xfail_if_allowed(self):
        # If phone uniqueness is expected, duplicates should be blocked (signals bug if not).
        phone = "+15551239999"
        u1, e1 = unique_user("dupphone1")
        u2, e2 = unique_user("dupphone2")

        r1 = create_user(u1, e1, phone=phone)
        assert r1.status_code == 201

        r2 = create_user(u2, e2, phone=phone)
        if r2.status_code == 201:
            pytest.xfail("BUG-015: Duplicate phone accepted; phone is not enforced unique.")
        assert r2.status_code in (400, 422)



class TestStatsAndInternal:
    # Suite: Stats & internal endpoints

    @pytest.mark.order(47)
    def test_stats_schema(self):
        # Stats endpoint should return the expected keys and types.
        r = stats(include_details=False)
        assert r.status_code == 200
        data = r.json()
        for k in ("total_users", "active_users", "inactive_users", "active_sessions", "api_version"):
            assert k in data

    @pytest.mark.order(48)
    def test_information_disclosure_stats_include_details_xfail(self):
        r = stats(include_details=True)

        # If this endpoint becomes protected later, treat that as a fix.
        if r.status_code in (401, 403):
            return

        assert r.status_code == 200
        data = r.json()

        # BUG-008 sentinel: include_details should NOT expose these unauthenticated.
        if "user_emails" in data or "session_tokens" in data:
            pytest.xfail("BUG-008: /stats?include_details=true exposes PII/session tokens without auth.")

    @pytest.mark.order(49)
    def test_bulk_create_hidden_endpoint(self):
        # Hidden bulk endpoint exists; ensure it's reachable and returns expected shape.
        users_payload = [
            {
                "username": f"bulk_{i}_{uuid.uuid4().hex[:6]}",
                "email": f"bulk_{i}_{uuid.uuid4().hex[:6]}@example.com",
                "password": "Abc12345!",
                "age": 22,
                "phone": "+15550000000",
            }
            for i in range(5)
        ]
        r = bulk_create(users_payload)
        assert r.status_code == 200
        body = r.json()
        assert "created" in body and "users" in body
        assert isinstance(body["created"], int)



class TestSecurityHardening:
    # Suite: Security — Input hardening

    @pytest.mark.order(50)
    def test_xss_attempt_username_rejected(self):
        # Reject obvious script injection via username validation.
        r = create_user("<script>alert('xss')</script>", f"{uuid.uuid4().hex[:6]}@example.com")
        assert r.status_code in (400, 422)
        assert "invalid characters" in r.text.lower()

    @pytest.mark.order(51)
    def test_xss_attempt_in_search_not_reflected(self):
        # Search response should not reflect raw query back into payload.
        payload = "<script>alert(1)</script>"
        r = search_users(payload, field="all", exact=False)
        assert r.status_code == 200
        assert "<script" not in r.text.lower()

    @pytest.mark.order(52)
    def test_null_byte_injection_rejected(self):
        # Null bytes should not be accepted in usernames.
        r = create_user("user\x00", f"{uuid.uuid4().hex[:6]}@example.com")
        assert r.status_code in (400, 422)
        assert "invalid characters" in r.text.lower()

    @pytest.mark.order(53)
    def test_path_traversal_attempt_not_matched(self):
        # Path-like search terms should not cause unintended behavior.
        r = httpx.get(f"{BASE_URL}/users/../../../etc/passwd", timeout=10)
        assert r.status_code in (404, 400)

    @pytest.mark.order(54)
    def test_http_method_override_patch_not_allowed(self):
        # Unsupported HTTP methods should be rejected.
        r = httpx.request("PATCH", f"{BASE_URL}/users/1", timeout=10)
        assert r.status_code == 405

    @pytest.mark.order(55)
    def test_content_type_validation_users(self):
        # Non-JSON payloads should be rejected by the /users endpoint.
        r = httpx.post(
            f"{BASE_URL}/users",
            data="not json",
            headers={"Content-Type": "text/plain"},
            timeout=10,
        )
        assert r.status_code in (400, 415, 422)

    @pytest.mark.order(56)
    def test_cors_headers_options(self):
        # OPTIONS behavior is documented; CORS middleware may or may not be configured.
        r = httpx.options(f"{BASE_URL}/users", timeout=10)
        assert r.status_code in (200, 405)



class TestPerformanceAndConcurrency:
    # Suite: Performance & concurrency

    @pytest.mark.perf
    @pytest.mark.order(57)
    def test_create_user_under_threshold(self):
        # Create user latency sanity check (soft target).
        _ = httpx.get(f"{BASE_URL}/health", timeout=10)  # warm-up
        uname, email = unique_user("perf")
        t0 = time.perf_counter()
        r = create_user(uname, email)
        dt_ms = (time.perf_counter() - t0) * 1000
        assert r.status_code in (201, 400)
        assert dt_ms < PERF_THRESHOLD_MS, f"Create user took {dt_ms:.2f}ms (threshold={PERF_THRESHOLD_MS}ms)"

    @pytest.mark.perf
    @pytest.mark.order(58)
    def test_list_users_under_threshold(self):
        # List users latency sanity check (soft target).
        _ = httpx.get(f"{BASE_URL}/health", timeout=10)  # warm-up
        t0 = time.perf_counter()
        r = list_users(limit=10, offset=0)
        dt_ms = (time.perf_counter() - t0) * 1000
        assert r.status_code == 200
        assert dt_ms < PERF_THRESHOLD_MS, f"List users took {dt_ms:.2f}ms (threshold={PERF_THRESHOLD_MS}ms)"

    @pytest.mark.perf
    @pytest.mark.order(59)
    def test_pagination_performance(self):
        # Pagination shouldn't degrade significantly under modest data volume.
        for _ in range(15):
            u, e = unique_user("pgperf")
            create_user(u, e)

        t0 = time.perf_counter()
        r = list_users(limit=10, offset=0, sort_by="id", order="asc")
        dt_ms = (time.perf_counter() - t0) * 1000
        assert r.status_code == 200
        assert dt_ms < PERF_PAGINATION_THRESHOLD_MS, (
            f"Pagination took {dt_ms:.2f}ms (threshold={PERF_PAGINATION_THRESHOLD_MS}ms)"
        )

    @pytest.mark.perf
    @pytest.mark.order(60)
    def test_parallel_user_creation_threadpool(self):
        # Concurrent creates should not crash or return duplicate ids.
        def worker(ix: int):
            uname, email = unique_user(f"cc{ix}")
            headers = {"x-real-ip": f"198.51.100.{ix % 250 + 1}"}
            return create_user(uname, email, headers=headers)

        n = 10
        ids = []
        statuses = []
        with ThreadPoolExecutor(max_workers=10) as ex:
            futs = [ex.submit(worker, i) for i in range(n)]
            for f in as_completed(futs):
                resp = f.result()
                statuses.append(resp.status_code)
                if resp.status_code == 201:
                    ids.append(resp.json().get("id"))

        assert sum(1 for s in statuses if s == 201) >= 6
        ids = [i for i in ids if isinstance(i, int)]
        assert len(ids) == len(set(ids)), "Duplicate user IDs detected in concurrent create (race sentinel)"



class TestSecuritySignals:
    # Suite: Security — Abuse & timing signals

    @pytest.mark.security
    @pytest.mark.order(61)
    def test_rate_limit_enforced_on_create_user(self):
        # Rate limit should kick in after enough requests from the same IP.
        headers = {"x-real-ip": "203.0.113.5"}
        got_429 = False
        for _ in range(105):
            u, e = unique_user("rl")
            r = create_user(u, e, headers=headers)
            if r.status_code == 429:
                got_429 = True
                break
        assert got_429, "Expected 429 after >100 create requests/min from same IP"

    @pytest.mark.security
    @pytest.mark.order(62)
    def test_brute_force_protection_sentinel_xfail(self):
        # Repeated bad logins should ideally be throttled/locked out (signal if not).
        uname, email = unique_user("bf")
        pw = "Abc12345!"
        cr = create_user(uname, email, password=pw)
        assert cr.status_code == 201

        statuses = []
        for i in range(8):
            r = login(uname, f"wrong_password_{i}")
            statuses.append(r.status_code)

        if all(s == 401 for s in statuses):
            pytest.xfail("BUG-013: No brute-force protection on /login (no lockout/throttle observed).")

    @pytest.mark.security
    @pytest.mark.order(63)
    def test_authentication_timing_attack_sentinel_xfail(self):
        uname, email = unique_user("timing")
        pw = "Abc12345!"
        cr = create_user(uname, email, password=pw)
        assert cr.status_code == 201

        samples_invalid_user = []
        samples_wrong_pass = []

        # warm-up
        login(uname, pw)

        for _ in range(8):
            t0 = time.perf_counter()
            login(f"nonexistent_{uuid.uuid4().hex[:6]}", "whatever")
            samples_invalid_user.append((time.perf_counter() - t0) * 1000)

            t1 = time.perf_counter()
            login(uname, f"wrong_{uuid.uuid4().hex[:6]}")
            samples_wrong_pass.append((time.perf_counter() - t1) * 1000)

        med_invalid = statistics.median(samples_invalid_user)
        med_wrong = statistics.median(samples_wrong_pass)
        diff = med_wrong - med_invalid

        if diff > TIMING_ENUM_THRESHOLD_MS:
            pytest.xfail(
                f"BUG-014: Timing difference suggests user enumeration risk "
                f"(median wrong_pass={med_wrong:.1f}ms vs invalid_user={med_invalid:.1f}ms, diff={diff:.1f}ms)"
            )