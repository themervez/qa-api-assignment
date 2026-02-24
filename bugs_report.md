# Bug Report — User Management API (v1.0.0)

> **Scope:** User Management API (v1.0.0), Assignment doc (`QA_ASSIGNMENT.md`), Swagger UI, seed data & docs  
>
> **Provided** `pytest` run output + `tests/test_api.py` (PASS/FAIL/XFAIL sentinels) + white-box review of `main.py`

---

## 1) Automated test outcome summary

- **Automated Collected:** 66 tests  
- **Automated Result:** **53 passed, 4 failed, 9 xfailed**

### Release blockers

**All 4 FAILs are explained by one root cause:** **`GET /users/search` is unreachable** due to **route shadowing** — see **BUG-006**.  
Because of this, `/users/search` requests are routed to `GET /users/{user_id}`, and since the path segment `"search"` cannot be parsed as an integer, the API returns **400**.

**Failing tests (all caused by BUG-006):**
- `TestUsersSearch::test_search_partial_and_exact` → 400
- `TestUsersSearch::test_search_email_exact_flag_behavior_sentinel_xfail` → 400 *(fails before reaching its intended sentinel)*
- `TestUsersSearch::test_unicode_security_search_query` → 400
- `TestSecurityHardening::test_xss_attempt_in_search_not_reflected` → 400

**Note (blocked sentinel):**
- `TestUsersSearch::test_search_email_exact_flag_behavior_sentinel_xfail` was designed to detect **BUG-007** once `/users/search` is reachable; however, it currently **fails early** due to **BUG-006**, so **BUG-007 cannot be evaluated** yet.

**Additional release blocker (Critical, even if XFAIL):**
- **BUG-001** — Username case-collision can overwrite an existing user (**data loss**). Even though this appears as an “XFAIL sentinel” in automation, it should be treated as a **release blocker** based on product risk.

### CI/CD note
- XFAIL tests in `test_api.py` are **defect sentinels**: they should remain XFAIL *only while the defect exists*. Once fixed, the XFAIL should be removed (or flipped to normal assertions) so CI becomes a clean signal.

---

## 2) Automation traceability

| Test result in run | Automated sentinel label (as in `test_api.py`) | Test name | Report bug ID | Notes                                                                                   |
|---|------------------------------------------------|---|---|-----------------------------------------------------------------------------------------|
| XFAIL | BUG-001                                        | `TestUsersCreate::test_case_collision_overwrite_sentinel_xfail` | **BUG-001** | Data loss (release blocker).                                                            |
| XFAIL | BUG-002                                        | `TestUsersReadList::test_pagination_limit_off_by_one_sentinel_xfail` | **BUG-002** | Off-by-one pagination.                                                                  |
| XFAIL | BUG-003                                        | `TestUsersUpdate::test_authorization_bypass_attempt_foreign_update_xfail` | **BUG-003** | Missing ownership/RBAC on update.                                                       |
| XFAIL | BUG-009                                        | `TestUsersUpdate::test_session_hijacking_attempt_token_not_ip_bound_xfail` | **BUG-009** | Token replay/hijack risk (not IP-bound).                                                |
| XFAIL | BUG-005                                        | `TestUsersDelete::test_delete_user_authorization_bypass_xfail` | **BUG-005** | Missing ownership/RBAC on delete.                                                       |
| FAIL | —                                              | `TestUsersSearch::test_search_partial_and_exact` | **BUG-006** | `/users/search` route shadowing → 400.                                                  |
| FAIL *(route shadowing; sentinel blocked)* | BUG-007 | `TestUsersSearch::test_search_email_exact_flag_behavior_sentinel_xfail` | **BUG-006 / BUG-007** | Fails due to **BUG-006** before reaching the **BUG-007** email exact/case sentinel.     |
| FAIL | —                                              | `TestUsersSearch::test_unicode_security_search_query` | **BUG-006** | Same root cause → 400.                                                                  |
| FAIL | —                                              | `TestSecurityHardening::test_xss_attempt_in_search_not_reflected` | **BUG-006** | Same root cause → 400.                                                                  |
| XFAIL | BUG-008                                        | `TestStatsAndInternal::test_information_disclosure_stats_include_details_xfail` | **BUG-008** | Sensitive data exposure on `/stats?include_details=true`.                               |
| XFAIL | BUG-015                                        | `TestUsersDelete::test_duplicate_phone_rejected_or_xfail_if_allowed` | **BUG-015** | Duplicate phone allowed.                                                                |
| XFAIL | BUG-013                                        | `TestSecuritySignals::test_brute_force_protection_sentinel_xfail` | **BUG-013** | No brute-force throttling on `/login`.                                                  |
| XFAIL | BUG-014                                        | `TestSecuritySignals::test_authentication_timing_attack_sentinel_xfail` | **BUG-014** | Timing differences allow username enumeration.                                          |
| PASS *(but undesired behavior)* | —                               | `TestUsersDelete::test_soft_deleted_user_update_returns_unchanged` | **BUG-004** | API returns 200 but no-ops on inactive user.                                            |
| PASS *(XFAIL triggers only if condition observed)* | BUG-023 | `TestUsersReadList::test_sorting_created_at_string_sort_quality_signal` | **BUG-023** | XFAIL triggers only if non-monotonic order is observed.                                 |

---


## Severity conventions
- **Critical:** blocks a documented endpoint or enables serious compromise/data loss
- **High:** major security/authorization issue or major functional defect
- **Medium:** incorrect behavior that misleads clients or creates exploitable weakness
- **Low:** contract/documentation/semantics issues with limited impact

---

## BUG-001: Username case-collision can overwrite an existing user (data loss)
**Severity:** Critical  
**Category:** Data Integrity/Validation

**Description:**  
`POST /users` checks duplicates using the raw `username` string, but the user is stored under `username.lower()` in `users_db`. Creating the “same” username with different casing can overwrite the existing record.

**Where in code:** `create_user()` — duplicate check vs write key mismatch

**Steps to Reproduce:**
1. `POST /users` with
```text
{
  "username": "CaseOW",
  "email": "a1@example.com",
  "password": "password123",
  "age": 18,
  "phone": "+905512345567"
}
```
```text
→ note returned `id`.
```
2. `POST /users` with
```text
{
  "username": "CASEOW",
  "email": "a2@example.com",
  "password": "password123",
  "age": 18,
  "phone": "+905512345568"
}
```
3. `GET /users/{id_from_step_1}`.

**Expected Result:**  
Second create should be rejected as a duplicate (typically **409**, or 400/422).

**Actual Result:**  
Second create can succeed (201) and overwrite the existing record stored under the lowercase key.

**Impact:** Data loss + account takeover style confusion.

**Evidence:**
- `Step 1` Swagger- (Create CaseOW – 201 Created, id=17): https://imgur.com/a/TSYD9pE
- `Step 2` Swagger- (Create CASEOW – duplicate accepted, id=18): https://imgur.com/a/l6uiMfW
- `Step 3` Swagger- (GET /users/17 – original record missing): https://imgur.com/a/oOdVU0f

---

## BUG-002: `/users` pagination returns `limit + 1` records (off-by-one)
**Severity:** High  
**Category:** Logic/Pagination

**Description:**  
`GET /users` slices results as `offset : offset + limit + 1`, returning one extra user.

**Where in code:** `list_users()` — pagination slice uses offset : offset + limit + 1

**Steps to Reproduce:**
1. Ensure at least 6 users exist.
2. Call `GET /users?limit=5&offset=0`.
3. Observe the number of items in the response array.

**Expected Result:**  
Response contains **≤ limit** items.

**Actual Result:**  
Response contains **limit + 1** items.

**Evidence:**
- `Step 1` Swagger- Ensure at least 6 users exist: https://www.loom.com/share/32e2e62c31304e618f16e6371e6cac6b
- `Step 2` Swagger- (Returned items: 6 (expected max 5)): https://www.loom.com/share/b914cf8d08074868886f289cb4956501
- `Step 3` Observed on Loom video - (Swagger-(Response contains 6 items)): https://www.loom.com/share/b914cf8d08074868886f289cb4956501

---

## BUG-003: Any authenticated user can update any other user (missing authorization)
**Severity:** High  
**Category:** Authorization

**Description:**  
`PUT /users/{id}` only checks that the Bearer token exists (session is valid). It does **not** restrict updates to the owning user (or an admin role). Any logged-in user can modify any user by ID.

**Where in code:** `update_user()`; verify_session() — session exists but no owner/RBAC enforcement

**Steps to Reproduce:**
1. Create User A as: 
```text
{
  "username": "userA_case",
  "email": "userA_case@example.com",
  "password": "password123",
  "age": 60,
  "phone": "+905500000001"
}
```
2. Login as user A → obtain token.

3. Create user B as 
```text
{
  "username": "userB_case",
  "email": "userB_case@example.com",
  "password": "password123",
  "age": 60,
  "phone": "+905500000002"
}
```
```text
→ note `B.id`.
```
4. `PUT /users/{B.id}` with A’s token and payload like `{ "email": "updateemail@example.com" }`.

**Expected Result:**  
403 Forbidden (or a defined RBAC policy).

**Actual Result:**  
200 OK and user B is updated.

**Evidence:**
- `Step 1` (Postman- Created User A): https://imgur.com/a/grVCEpe
- `Step 2` (Postman- Login as User A (token obtained)): https://imgur.com/a/P2PmzkB
- `Step 3` (Postman- Created User B (B.id:22 observed on the example)): https://imgur.com/a/rXjnRdy
- `Step 4` (Postman- PUT /users/{B.id} with using User A token – 200 OK, User B updated ): https://imgur.com/a/Nd8OeP4
- `Step 5` (Postman- GET /users/{B.id} → confirmed that User B updated): https://imgur.com/a/CsqJOL7

**Fix Recommendation:**  
Bind session to user and enforce `session_user == target_user` (or implement roles)

---

## BUG-004: Updating a soft-deleted user returns `200 OK` but silently does nothing
**Severity:** Medium  
**Category:** Logic/API Semantics

**Description:**  
If a target user has `is_active == False`, `PUT /users/{id}` returns **200** and the unchanged user object instead of rejecting the update. This is misleading to clients.

**Where in code:** `update_user()` — inactive user returns 200 with unchanged object

**Steps to Reproduce:**
1. Create a normal user (`soft_del_user`) via `POST /users` and note the returned `id`.
2. Create another user (`deleter_user`) who will perform the delete action.
3. Soft-delete `soft_del_user` by calling  
   `DELETE /users/{soft_del_user.id}` using **Basic Auth** of `deleter_user`.  
   → The response confirms deletion and shows `"is_active": false`.
4. Login as any valid user (e.g. `deleter_user`) via `POST /login` and obtain a **Bearer token**.
5. Attempt to update the soft-deleted user by calling  
   `PUT /users/{soft_del_user.id}` with the Bearer token and a payload that changes fields (e.g. `email`, `age`).

**Expected Result:**  
Reject with a clear status (commonly 404, 409, or 423) and message.

**Actual Result:**  
- API returns `200 OK`
- Response body contains the original, unchanged user data
- `"is_active"` remains `false`
- Updated fields (`email`, `age`) are silently ignored

This gives the false impression that the update succeeded.

**Evidence:**
- `Step 1` (Postman- Created soft_del_user ("id": 1,"is_active": true)): https://imgur.com/a/Sd11obH
- `Step 2` (Postman- Created deleter_user ("username": "deleter_user","password": "password123")): https://imgur.com/a/rsCCzei
- `Step 3` (Postman- Deleted soft_del_user(id:1):(is_active=false) via deleter_user: https://imgur.com/a/user-management-api-bug-004-step-3-Z0atkDP
- `Step 4` (Postman- PUT /users/{soft_del_user's id} with new email/age → "200 OK" but response unchanged, "is_active=false")): https://imgur.com/a/nDw1BsQ
- `Step 5` (Postman- GET /users/{soft_del_user's id} → email/age still unchanged): https://imgur.com/a/jclNyC0

---

## BUG-005: Any valid Basic-auth user can delete any other user (missing authorization)
**Severity:** High  
**Category:** Authorization

**Description:**  
`DELETE /users/{id}` validates Basic credentials for *some* user but does not restrict deletes to the owning user or admins.

**Where in code:** `delete_user()`; verify_credentials() — credentials validated but no requester-vs-target authorization

**Steps to Reproduce:**
1. Create a User A or use Seed data (for Basic auth).
2. Create a Victim User → note `victim_user.id`.
3. `DELETE /users/{victim_user.id}` using Basic auth for User A.
4. `GET /users/{victim_user.id}` to verify the victim is now inactive (`is_active: false`)

**Expected Result:**  
403 Forbidden unless requester is authorized.

**Actual Result:**  
API returns **200 OK** and the victim user becomes inactive (`is_active: false`).

**Evidence:**
- `Step 1` Run seed_data and choose a user for Basic auth (e.g. for this step:john_doe): https://imgur.com/a/fNxaDBX
- `Step 2` Postman- Created victim_user ("id": 13): https://imgur.com/a/3UVJ08z
- `Step 3` Postman- Deleted victim_user(id:13):(is_active=false) via user john_doe: https://imgur.com/a/icVmIex
- `Step 4` Postman- GET /users/{victim_user's id} → for checking is active or not: https://imgur.com/a/Ih83M8w

---

## BUG-006: `/users/search` is broken due to route shadowing by `/users/{user_id}`
**Severity:** Critical  
**Category:** Functional/Routing

**Description:**  
GET /users/{user_id} route is registered before GET /users/search. Because the path parameter is not constrained at the routing layer, /users/search is matched by the dynamic route first (route shadowing). 
The handler then attempts to parse "search" as an integer and returns 400.

**Where in code:** get_user() route is declared before search_users() route; get_user(user_id: str) matches /users/search

**Preconditions:**
- No authentication required

**Steps to Reproduce:**
1. Execute the request `GET /users/search?q=test&field=all&exact=false`.

**Expected Result:**  
200 OK with a JSON array (possibly empty).

**Actual Result:**  
400 Bad Request, routed to `GET /users/{user_id}` instead of /users/search, error: `Invalid user ID format: search`.

**Evidence:**
- `Step 1` Executed the request `GET /users/search?q=test&field=all&exact=false`: https://imgur.com/a/Tz9sHht
---

## BUG-007: `/users/search` ignores `exact=true` for email search and applies inconsistent case handling
**Severity:** Medium  
**Category:** Logic / Search  
**Status:** Blocked by BUG-006 (route shadowing prevents runtime verification)

**Description:**  
In `/users/search`, the email search logic does not respect the `exact=true` flag.  
For `field=email`, the code always performs substring matching using `in`, regardless of the `exact` parameter.  
Additionally, when `exact=false`, the query is lowercased, but the comparison is performed against the original email value (not normalized), which results in inconsistent case handling (i.e., it is not reliably case-insensitive).  
This is inconsistent with the username search logic and creates ambiguous search semantics.

**Where in code:**  
`search_users()` — email search branch ignores `exact` and performs non-normalized (case-inconsistent) comparison

**Steps to Reproduce:**
1. Execute the request `GET /users/search?q=test&field=email&exact=true`.
2. Observe that the request returns **400 Bad Request** due to **BUG-006** (route shadowing), so currently the email search logic cannot be exercised via the runtime reproduction.

**Expected Result:**  
- When `exact=true`:  
  - Email matching should use exact comparison (`==`), with explicitly defined case sensitivity.
- When `exact=false`:  
  - Email matching should be case-insensitive and use partial matching, consistent with username

**Actual Result (from white-box review):**
- For `field=email`, the implementation always uses substring matching (`if search_pattern in user["email"]`) even when `exact=true`.
- When `exact=false`, `search_pattern` is lowercased, but `user["email"]` is not, causing effectively **case-sensitive** behavior for many inputs.

**Evidence:**
- **Runtime:** Blocked by **BUG-006** (`/users/search` returns 400 before reaching search logic).
- **White-box:** In `search_users()`, the email branch uses:
  - `search_pattern = q.lower() if not exact else q`
  - `if search_pattern in user["email"]:` (no equality check for `exact=true`, and no lowercasing of `user["email"]`)

```text
@app.get("/users/search")
def search_users(
    q: str = Query(..., min_length=1),
    field: str = Query("all", regex="^(all|username|email)$"),
    exact: bool = False,
):
    results = []
    search_pattern = q.lower() if not exact else q
    for username, user in users_db.items():
        matched = False
        if field == "all" or field == "username":
            if exact:
                if user["username"] == search_pattern:
                    matched = True
            else:
                if search_pattern in user["username"].lower():
                    matched = True
        if field == "all" or field == "email":
            if search_pattern in user["email"]:
                matched = True
        if matched:
            results.append(UserResponse(**user))
    return results
```
---

## BUG-008: `/stats?include_details=true` leaks emails and active session tokens (unauthenticated)
**Severity:** High  
**Category:** Security/Privacy

**Description:**  
`GET /stats` is unauthenticated and, with `include_details=true`, discloses user emails and active session tokens.

**Where in code:** `get_stats()` — include_details exposes user_emails and session_tokens without auth

**Steps to Reproduce:**
1. Ensure at least one active session exists (login).
2. Execute the request `GET /stats?include_details=true`.

**Expected Result:**  
Protect endpoint (admin-only) and never return session tokens; mask PII if needed.

**Actual Result:**  
Response includes `user_emails` and `session_tokens`.

**Security Impact:**  
Exposure of active session tokens enables account takeover without credential compromise.

**Evidence:**
- `Step 1` Postman- Login as any valid user (POST /login)-(Seed data: jane_smith): https://imgur.com/a/4trA8AI
- `Step 2` Postman- Executed the request `GET /stats?include_details=true` without Authorization header: https://www.loom.com/share/5fd81a9f40ed4dd2be8d0a0234a8195e
-  (Response body contains `user_emails` and `session_tokens`)
- Automated detection:  
  `TestStatsAndInternal::test_information_disclosure_stats_include_details_xfail`
---

## BUG-009: Session token is not bound to client IP (replay/hijack risk)
**Severity:** High  
**Category:** Security/Session Management

**Description:**   
Session records store the client IP address at login time, but `verify_session()` never compares the incoming request IP with the stored value. As a result, a stolen token can be replayed from any IP address.

**Where in code:** `verify_session()`; get_client_ip() — session stores ip but verify_session does not validate ip

**Steps to Reproduce:**
1. Login from IP A to obtain token.
2. Execute the request `PUT /users/{id}` from IP B using the same token.

**Expected Result:**  
Reject token use from a different IP (or remove the stored IP to avoid a false sense of binding).

**Actual Result:**  
Token works regardless of IP.

**Evidence:**
- `Step 1` (Postman– POST /login from IP A `198.51.100.22`, token issued): https://imgur.com/a/eDUSw4j
- `Step 2` (Postman– PUT /users/{id} from IP B `203.0.113.50` using the same token, 200 OK): https://www.loom.com/share/43e64361850046fcbe6dc12c114ce95a
- (Same token accepted from different IPs)
- Automated detection:
  `TestUsersUpdate::test_session_hijacking_attempt_token_not_ip_bound_xfail`

---

## BUG-010: Session expiry is not enforced (tokens do not expire) 
**Severity:** High  
**Category:** Security/Session Management

**Description:**  
Login response includes an `expires_in` value (e.g., 86400 seconds) and sessions store `expires_at`, but `verify_session()` does not enforce expiry (expiry validation is commented out). 
As a result, tokens may remain valid beyond the advertised TTL; remain valid until explicit logout or server restart.

**Where in code:** `verify_session()` — session expiry check is commented out/ not applied

**Expected Result:**
After the advertised TTL (`expires_in`) elapses, the token should be rejected with **401** (e.g., "Session expired").

**Actual Result:**
Tokens are not expired based on `expires_at` (expiry enforcement is missing), so they can remain valid beyond the advertised TTL.

**Evidence:**
- `Step 1` (Postman–POST /login response shows `expires_in: 86400` and returns a token): https://imgur.com/a/eDUSw4j
- `Step 2` (White box review– `verify_session()` expiry check is commented out / not applied): 
```text
def verify_session(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.replace("Bearer ", "")
    if token not in sessions:
        raise HTTPException(status_code=401, detail="Invalid session")
    session = sessions[token]
    # if datetime.now() > session["expires_at"]:
    #     raise HTTPException(status_code=401, detail="Session expired")
    return session["username"]
```
```text
//expiry
@app.post("/login")
def login(login_data: LoginRequest, client_ip: str = Depends(get_client_ip)):
    .....
    sessions[session_token] = {
        "username": username_lower,
        "created_at": datetime.now(),
        "expires_at": datetime.now() + timedelta(hours=24),
        "ip": client_ip,
    }
    return {"token": session_token, "expires_in": 86400, "user_id": user["id"]}
```
---

## BUG-011: Password hashing is insecure (MD5 + static salt)
**Severity:** High  
**Category:** Security/Cryptography

**Description:**  
Passwords are hashed with **MD5** using a **hardcoded, global static salt** (`static_salt_2024`). MD5 is a fast hash and is unsuitable for password storage; a global static salt does not provide per-user uniqueness, making hashes more vulnerable to offline cracking.

**Where in code:** `hash_password()` — MD5 + static salt

**Expected Result:**
Passwords should be stored using a password hashing mechanism suitable for credential storage, such as a slow, adaptive hash (e.g., **Argon2id**, **bcrypt**, or **scrypt**) with a **per-user random salt** and appropriate work factors.

**Actual Result:**   
Passwords are stored as MD5(`static_salt_2024` + password).

**Evidence:**
- `White box review` – `hash_password()` uses MD5 with a global hardcoded salt `static_salt_2024`):
```text
def hash_password(password: str) -> str:
    salt = "static_salt_2024"
    return hashlib.md5(f"{salt}{password}".encode()).hexdigest()
```
---

## BUG-012: Rate limiter is not thread-safe / not consistent under concurrency
**Severity:** Medium  
**Category:** Concurrency/Reliability

**Description:**  
`request_counts` and `last_request_time` are global dicts mutated without locking. Under concurrent access (multiple threads) this can produce incorrect 429s or missed throttles. Additionally, in multi-worker deployments each worker has its own in-memory limiter state (per-process), making limits inconsistent.

**Where in code:** `verify_rate_limit()` — global dicts mutated without locking; per-process state

**Expected Result:**  
Thread-safe limiter state and deployment-consistent behavior (shared store / middleware).

**Actual Result:**
Rate limiting relies on unsynchronized in-memory state, leading to non-deterministic behavior under concurrent load.

**Evidence:**
-  **White box review**:
- `request_counts` and `last_request_time` are global dicts.
- `verify_rate_limit()` performs read/modify/write (`+= 1`, assignments) without any lock/synchronization.
- Rate limiting is enforced via `create_user()` calling `verify_rate_limit(client_ip)`.

---

## BUG-013: No brute-force protection on `/login`
**Severity:** Medium  
**Category:** Security/Authentication

**Description:**  
Rate limiting is applied only to `POST /users` (create). The `/login` endpoint has no throttling/backoff/lockout mechanism, so it can be hit repeatedly for credential stuffing or brute-force attempts. 
The artificial sleep delays do not meaningfully mitigate brute force at scale.

**Where in code:**  
`/login` — no rate limiting/backoff; `verify_rate_limit()` is not applied to login

**Steps to Reproduce:**
1. Create a User or use credentials from Seed data.
2. Send repeated `POST /login` requests with the correct username and wrong passwords in a short period.

**Expected Result:**  
Brute-force protection should be present for `/login` (e.g., rate limiting, progressive backoff, or temporary lockout) keyed by IP and/or username after repeated failures.

**Actual Result:**  
Requests continue to return **401** indefinitely without throttling (e.g., no **429**, no lockout/cooldown).

**Evidence:**
- `Step 1` (Postman– (Seeded Data(`john_doe`)) Repeated POST /login attempts with wrong passwords; responses remain 401 with no 429/lockout): https://imgur.com/a/OMPdtMF
- `Step 2` (Postman Runner– 40 iterations of POST /login with wrong password; all responses 401, no 429/lockout observed): https://www.loom.com/share/c19feabfe5ce4bae8fb98e32abf4c4d7

---

## BUG-014: `/login` timing differences allow username enumeration
**Severity:** Medium  
**Category:** Security/Authentication

**Description:**  
The `/login` endpoint introduces different response delays (**~0.05s** for non-existent usernames vs **~0.1s** for wrong passwords). 
This consistent timing difference is observable over multiple requests and enables timing-based username enumeration.

**Where in code:**  
`/login` — different sleep timings for unknown username vs wrong password

**Steps to Reproduce:**
1. Repeatedly call `POST /login` with a non-existent username and measure the response times.
2. Repeatedly call `POST /login` with a valid username and an incorrect password and measure the response times.
3. Observe that responses for the valid username case are consistently slower.

**Expected Result:**  
Authentication failures should have near-constant response timing regardless of whether the username exists.

**Actual Result:**  
A consistent and measurable timing gap is observed between “wrong username” and “wrong password” cases.

**Impact:**  
The timing gap can be used to determine whether a username exists, enabling user enumeration and making brute-force/credential-stuffing attacks more effective (especially combined with BUG-013).

**Evidence:**
- `Step 1` (Postman– `POST /login` request with a non-existent username show consistently lower response time): https://imgur.com/a/rdQOzEz
- `Step 2` (Postman– `POST /login` requests with a valid username and wrong password show consistently higher response time): https://imgur.com/a/7ARqYKB
- `Step 3` (Postman Runner– Comparison Repeated 20 `POST /login` requests – a stable timing gap between the two cases confirms timing-based username enumeration): https://www.loom.com/share/311844834b9f443ca20dec518839dc58

---

## BUG-015: Duplicate phone numbers are allowed (missing uniqueness constraint)
**Severity:** Medium  
**Category:** Data Integrity/Validation

**Description:**  
The API allows multiple users to register with the **same phone number**. If phone numbers are intended to be unique identifiers (common in user systems), this creates integrity issues (account recovery, contactability, downstream joins).  
If uniqueness is **not** a business rule, this should be explicitly documented.

**Where in code:** `create_user()` — no phone uniqueness check

**Steps to Reproduce:**
1. `POST /users` with `phone="+905556667788"` → **201 Created**.
2. `POST /users` with a different username/email but the **same** phone → **201 Created**.

**Expected Result:**  
Either:
- 400/409 with a clear message (e.g., `"phone already exists"`), **or**
- Explicit documentation that phone numbers are not unique.

**Actual Result:**  
Multiple users can be created with the same phone number.

**Evidence:**
- `Step 1` (Postman– Created first user with phone "+905556667788" → 201 Created): https://imgur.com/a/KSYr7Dj
- `Step 2` (Postman– Created second user with different username/email but same phone "+905556667788" → 201 Created): https://imgur.com/a/rSsMr8s
- `Step 3` (Swagger– GET/users confirms both users exist with same phone number): https://imgur.com/a/J3BRnyn

---

## BUG-016: Phone validation is missing on update (invalid phones can be stored)
**Severity:** Medium  
**Category:** Data Integrity/Validation

**Description:**  
`UserCreate` validates phone format, but `UserUpdate` does not. As a result, `PUT /users/{id}` can persist invalid phone strings, creating inconsistent data compared to the create flow.

**Where in code:**  
UserUpdate model; update_user() — no phone validator in update path

**Steps to Reproduce:**
1. Create a user and log in to obtain a Bearer token.
2. Call `PUT /users/{id}` with an invalid phone value (e.g., `{ "phone": "abc" }`).
3. Check the user (`GET /users/{id}`) and verify the invalid phone value is stored.

**Expected Result:**  
Reject invalid phone values on update with a validation error (typically 422/400), consistent with create-user validation rules.

**Actual Result:**  
`PUT /users/{id}` returns `200 OK` and the invalid phone value is persisted.

**Evidence:**
- `Step 1` (Postman– Created user with a valid phone → 201 Created; captured user id:16): https://imgur.com/a/L8rrDka
- `Step 2` (Postman– Logged in and obtained Bearer token → 200 OK): https://imgur.com/a/2WGNIUq
- `Step 3` (Postman– Updated user with invalid phone `"abc"` → 200 OK; invalid value accepted): https://imgur.com/a/PnDmRpy
- `Step 4` (Postman– GET /users/{id} confirms invalid phone is persisted): https://imgur.com/a/SOyyrOF

---

## BUG-017: Hidden `/users/bulk` endpoint is unauthenticated and silently drops failures
**Severity:** High  
**Category:** Security/Reliability/Documentation

**Description:**  
`POST /users/bulk` is excluded from the OpenAPI schema (`include_in_schema=False`) but is still publicly callable without authentication.  
The handler also swallows exceptions (`except: pass`), causing partial failures to be silently ignored—clients cannot learn which items failed or why. 
This creates an undocumented ingestion surface and makes misuse/debugging harder.

**Where in code:**   
`bulk_create_users()` — `include_in_schema=False` hides the endpoint from OpenAPI; broad `except: pass` swallows per-item failures.
- `White box review` confirms `include_in_schema=False` and a broad `except: pass`, so **failed items are silently dropped** and never reported back to the client.

**Steps to Reproduce:**
1. Call `POST /users/bulk` without authentication, with a payload that is **schema-valid** but includes a **runtime failure** item (e.g., duplicate `username` within the batch).
- Observe the endpoint returns `200 OK` and a response shaped like `{"created": N, "users": [...]}`.
- Confirm that `created` is less than the submitted item count, but the response provides **no per-item error details** (silent drop).

**Expected Result:**  
Endpoint should be authenticated (or removed), documented, and return per-item success/error details (or fail the entire batch with a clear 4xx error).

**Actual Result:**  
Endpoint is publicly accessible; invalid items are silently ignored and no per-item error details are returned.

**Evidence:**
- `Step 1` (Postman– POST `/users/bulk` without auth using a schema-valid payload containing **duplicate username** → `200 OK`; response returns `created < submitted_count` and only successful users): https://www.loom.com/share/fec97e025d2e478a9215b2d84eb05f64
- (No `Authorization` header was provided, but the endpoint is still accessible)
- (Response contains no per-item failure details; failing item is silently dropped)

**Impact:**  
Undocumented endpoints expand attack surface; unauth access plus silent failure makes misuse harder to detect and debug.

**Note:**  
Schema-invalid payloads (e.g., invalid email format) are rejected with `422` by FastAPI validation before the handler executes.  
The “silent drop” behavior occurs for runtime failures during creation (e.g., duplicates).

**Additional Risk (Silent rate-limit failures):**  
`bulk_create_users()` internally calls `create_user()` with a hardcoded client IP (`127.0.0.1`).  
Since `create_user()` enforces a per-IP rate limit (100 requests/minute), large bulk payloads can legitimately trigger `429 Rate Limit` errors during processing.  
However, because the bulk handler wraps each create operation in a broad `except: pass`, these rate-limit violations (as well as other runtime exceptions) are silently swallowed.  
As a result, the API may return `200 OK` with a partial success count while providing no indication that some records failed due to rate limiting rather than validation errors (e.g., duplicates).  
This makes the reported `"created"` count potentially misleading and significantly degrades observability in batch ingestion workflows.

---

## BUG-018: Password policy is weak (length-only)
**Severity:** Medium  
**Category:** Security/Validation

**Description:**  
Passwords are only validated by **minimum length (6)**. This allows extremely weak passwords (e.g., `"123456"`) and increases the risk of credential stuffing / guessing if this were production-like.

**Where in code:** UserCreate model — password only min_length=6

**Steps to Reproduce:**
1. Create a new user by calling `POST /users` with a weak password that meets only the minimum length requirement (e.g. `"123456"`).   
Observe that the user is successfully created (`201 Created`) despite the password lacking any complexity.
2. Authenticate using the same weak credentials via `POST /login`.
3. Check the created user via `GET /users/{id}` to confirm the account exists.

**Expected Result:**  
A stronger policy (e.g., length + complexity) 

**Actual Result:**  
The user is created successfully (`201 Created`) with a weak password such as `"123456"`, and the same credentials can be used to log in without any additional validation beyond a six-character minimum.

**Evidence:**
- `Step 1` (Postman– POST /users with weak password `"123456"` → **201 Created**; user accepted): https://imgur.com/a/8SmHiAx
- `Step 2` (Postman– POST /login with the same credentials → **200 OK**; token issued): https://imgur.com/a/SMrdGa7
- `Step 3` (Postman– GET /users/{id} confirms user exists after weak password create): https://imgur.com/a/wboYxtg

**Impact:**
Increases risk of credential stuffing / brute-force success

---

## BUG-019: `/health` “memory_*” fields are incorrect (string-length, not memory usage)
**Severity:** Low  
**Category:** Logic/Observability

**Description:**  
`/health` returns `memory_users` and `memory_sessions` computed as `len(str(users_db))` and `len(str(sessions))`, which measures the length of the string representation, not memory usage. Values will change with formatting and are not meaningful.

**Where in code:** `health_check()` — memory_* computed via len(str(...))

**Precondition:**   
Application should be restarted before the test to ensure a clean in-memory state.

**Steps to Reproduce:**
1. Call `GET /health` on a fresh application state (in-memory stores cleared) and note the values of `memory_users` and `memory_sessions`.
2. Create a single user using `POST /users`.
3. Call `GET /health` again.
4. Compare the `memory_*` values before and after the user creation.

**Expected Result:**  
The `/health` endpoint should not expose misleading “memory” metrics. Any reported fields should accurately represent what they claim to measure.

**Actual Result:**  
The `memory_users` and `memory_sessions` values change based on the string representation length of internal data structures rather than actual memory usage. 
The reported numbers increase or decrease with formatting and object content, making them misleading and not representative of real memory consumption.

**Evidence:**
- `Step 1` Postman– After restarting the application (no seed data, no logins), Executed `GET /health` → `memory_users: 2`, `memory_sessions: 2` (empty dict string length): https://imgur.com/a/hEGTM3R
- `Step 2` Postman– Executed `POST /users` to create a single user → **201 Created**: https://imgur.com/a/KWpTNSV
- `Step 3` Postman– Executed `GET /health` again (still no logins) → `memory_users` jumped from `2` to `303` while `memory_sessions` remained `2`: https://imgur.com/a/aLbgGoC    
  (Demonstrating that the metric tracks `len(str(users_db))` / `len(str(sessions))` rather than actual memory usage)
---

## BUG-020: Username allowlist is overly permissive (quotes/semicolon allowed)
**Severity:** Low  
**Category:** Input Validation/Data Hygiene

**Description:**  
`username` validation allows characters like single-quote (`'`), double-quote (`"`), and semicolon (`;`). While not immediately exploitable in this demo, these characters frequently cause issues in logs, exports, and downstream systems (and can amplify injection risks if usernames are later used in SQL/CSV contexts).

**Where in code:**  UserCreate.validate_username() — regex allows quotes/semicolon (`'" ;`)

**Steps to Reproduce:**
1. Call `POST /users` with a username containing special characters such as quotes and semicolons (e.g.,`jane\";test`).   
   Observe that the API accepts the username and creates the user successfully (`201 Created`).
2. Check `GET /users/{id}` to confirm the stored username includes these characters (typically lowercased).

**Expected Result:**  
Usernames should either be restricted to a clearly defined, safe character set (e.g., alphanumeric characters with `_` and `-`) or the currently permitted characters should be explicitly documented as part of the API contract.

**Actual Result:**  
The API accepts usernames containing characters like `'`, `"`, and `;` and successfully creates the user (`201 Created`). The stored username preserves these characters (usually normalized to lowercase), which can introduce downstream hygiene risks (logs/CSV/SQL contexts).

**Evidence:**
- `Step 1` Postman– Executed `POST /users` with username `jane\";test` → **201 Created**; username accepted: https://imgur.com/a/q2AwFyE
- `Step 2` Postman– Executed `GET /users/{id}` confirms the stored `username` includes `"` and `;` characters: https://imgur.com/a/8MoVuZL

**Recommendation:** Either document the accepted character set clearly or restrict it to a safer subset (e.g., alphanumeric, underscore, hyphen).

---

## BUG-021: Logout semantics are ambiguous (always 200 OK)
**Severity:** Low  
**Category:** API Semantics/UX

**Description:**  
`POST /logout` always returns **200 OK**, but the response semantics differ in a confusing way:
- Missing/invalid Authorization → `"No active session"`
- Random / unknown Bearer token → `"Logged out successfully"` (even though nothing was actually terminated)

This makes it hard for clients to know whether a token was valid or a logout took place, and can hide client bugs.

**Where in code:** `logout()` — always 200; ambiguous semantics

**Steps to Reproduce:**
1. Call `POST /logout` without providing an `Authorization` header.
2. Call `POST /logout` with an invalid or unknown Bearer token (e.g., `Bearer test-bearer-token`).
3. Create a valid session via `POST /login`.
4. Call `POST /logout` with the valid token. Compare the HTTP status codes and response messages returned in each case.

**Expected Result:**  
Either:
- **Strict semantics:** `401` for missing/invalid token, and `200/204` only for valid sessions, **or**
- **Idempotent semantics:** always `204` / `200` but with an explicit message like `"No active session"` when nothing was revoked, and documented behavior.

**Actual Result:**  
The `/logout` endpoint always returns `200 OK` regardless of session state.   
Missing or malformed authorization headers return `"No active session"`, while unknown Bearer tokens return `"Logged out successfully"`, even though no session was actually terminated.    
This makes it difficult for clients to distinguish between a successful logout and a no-op.

**Evidence:**
- `Step 1` Postman– Executed `POST /logout` without `Authorization` → **200 OK**, message: `"No active session"`: https://imgur.com/a/xtkUs71
- `Step 2` Postman– Executed `POST /logout` with an unknown Bearer token → **200 OK**, message: `"Logged out successfully"`: https://imgur.com/a/wwXWr1M
- `Step 3` Created valid session via `POST /login` (seed data: john_doe): https://imgur.com/a/ZWe0Lur
- `Step 4` Postman– Executed `POST /logout` with a valid token → **200 OK**, message: `"Logged out successfully"`: https://imgur.com/a/mjFcJ86

---

## BUG-022: OpenAPI contract gaps (schemas + hidden endpoints)
**Severity:** Low  
**Category:** Documentation/Contract Clarity

**Description:**
The published OpenAPI documentation does not fully reflect runtime behavior and reduces usability for API consumers:
- `/users/bulk` exists at runtime but is missing from the OpenAPI documentation (hidden route).
- `/users/search` does not clearly define a usable `200` response schema describing the returned list of user objects.

**Evidence:**
- Swagger UI / ReDoc navigation does not include `/users/bulk`, although the endpoint is callable at runtime.
- In Swagger UI / ReDoc, `/users/search` does not expose a clear `200` response schema for a list of users.

**Impact**
- Undocumented runtime endpoints increase integration risk and widen the surface area unexpectedly.
- Missing/unclear response schemas reduce the usefulness of the OpenAPI contract for client integration and automation.

**Fix Recommendation**
- Document `/users/bulk` in OpenAPI (or remove it from runtime if not intended to be public).
- Define an explicit response model for `/users/search` (e.g., `List[UserResponse]`).

---

## BUG-023: Sorting by `created_at` uses string conversion (fragile ordering implementation)  
**Severity:** Low  
**Category:** Logic/Maintainability  

**Description:**  
When calling `GET /users` with `sort_by=created_at`, the API sorts using `str(created_at)` instead of sorting by the datetime value itself.   
With the current `datetime` representation this will often *appear* correct, but the implementation is unnecessarily **fragile** and can become incorrect if the datetime representation changes (e.g., timezone-aware datetimes, different serialization/formatting).    
It also makes the intent less clear than sorting by the actual datetime field.

**Where in code:** `list_users()` — created_at sorted via str(created_at)

**Steps to Reproduce:**  
1. Create multiple users at different times.  
2. Execute the request `GET /users?sort_by=created_at&order=asc&limit=20&offset=0`  
3. Review ordering; note that a monotonicity failure may not reproduce consistently in the current setup (this is primarily a robustness/quality issue).

**Expected Result:**  
Users should be sorted by the actual datetime value (`created_at`) to ensure deterministic, intention-revealing ordering.

**Actual Result:**  
Sorting is performed using `str(created_at)` instead of datetime comparison.

**Evidence:**  
- **White box reviewing:**   
- In `list_users()`, when `sort_by == "created_at"`, sorting is performed using:
  `all_users.sort(key=lambda x: str(x[sort_by]), reverse=(order == "desc"))`
  which converts the datetime to string before comparison.
```text
if sort_by == "created_at":
    all_users.sort(
        key=lambda x: str(x[sort_by]),
        reverse=(order == "desc")
    )
else:
    all_users.sort(
        key=lambda x: x[sort_by],
        reverse=(order == "desc")
    )
```
---


## Quick severity recap (triage)
- **Critical:** BUG-001, BUG-006
- **High:** BUG-002, BUG-003, BUG-005, BUG-008, BUG-009, BUG-010, BUG-011, BUG-017
- **Medium:** BUG-004, BUG-007, BUG-012, BUG-013, BUG-014, BUG-015, BUG-016, BUG-018
- **Low:** BUG-019, BUG-020, BUG-021, BUG-022, BUG-023


# Notes / hardening recommendations (enhancements)
These are reasonable improvements beyond the explicit assignment/OpenAPI requirements. They should be tracked as **enhancements** (not defects), unless the product explicitly requires them:

- **Email uniqueness (policy decision):** Not enforced. If email must be unique, add a uniqueness check and standardize status codes (prefer 409 for conflicts).
- **Production hardening for diagnostics:** Even after fixing specific disclosure issues (e.g., BUG-008), consider restricting `/stats` and `/health` to trusted callers/admins in production environments.
- **Session hygiene (post-fix strengthening):** After addressing session issues (BUG-009 / BUG-010), consider shorter TTLs, token rotation, and optional binding to additional client signals (e.g., user-agent) to reduce replay risk.
- **Auditability:** Add structured logs and correlation IDs for security-relevant actions (login/logout, update/delete) to support incident response and troubleshooting.
