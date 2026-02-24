# test_report.md — User Management API (v1.0.0)

---

## 1. Executive Summary

### Automated test outcome (baseline run)
- **Collected:** 66  
- **Result:** **53 passed, 4 failed, 9 xfailed** (≈65s)  
- **Interpretation:** The suite uses **XFAIL defect sentinels** to keep the run informative while known issues remain reproducible.

### Key findings
- **Functional blocker:** `GET /users/search` is **unreachable** due to **route shadowing** (**BUG-006**). This breaks a documented assignment endpoint.
- **Data loss risk:** Username **case-collision overwrite** can erase or make earlier users unreachable (**BUG-001**).
- **Security risks (high impact):**
  - `/stats?include_details=true` leaks **PII + session tokens** without auth (**BUG-008**).
  - Sessions are **not IP-bound** (**BUG-009**) and **expiry is not enforced** (**BUG-010**).
  - Password storage is insecure (**MD5 + static salt**, **BUG-011**).
  - Missing authorization checks allow **updating/deleting other users** (**BUG-003**, **BUG-005**).
  - Hidden unauthenticated bulk ingestion endpoint silently drops failures (**BUG-017**).

### Risk assessment
- **Critical risk:** broken endpoint + data-loss bug.
- **High security risk:** token leakage and weak session/password handling significantly increase account takeover probability in any production-like environment.

---

## 2. Test Scope and Approach

### Scope (per assignment)
Endpoints covered (assignment list):
- Public: `GET /`, `POST /users`, `GET /users`, `GET /users/{user_id}`, `POST /login`, `POST /logout`
- Protected: `PUT /users/{user_id}`, `DELETE /users/{user_id}`
- Additional: `GET /users/search`, `GET /stats`, `GET /health`

### What was tested
- **Positive / negative** flows for all endpoints
- **Validation & boundary** checks (username rules, email, age, phone, password length)
- **Auth flows** (Basic + Bearer) and session behavior
- **Security signals** (timing, brute-force, disclosure, input hardening)
- **Performance & concurrency** sanity checks (soft targets)
- **Contract checks** (basic response schema expectations)

### What was not measured
- **Code coverage %** was not measured in this submission (no `pytest-cov` run output was provided).  
  Recommendation: add a coverage run (e.g., `pytest --cov --cov-report=term-missing`) once final.

---

## 3. Test Environment

- **Framework:** `pytest` + `httpx`
- **Target:** local FastAPI server (default `BASE_URL=http://127.0.0.1:8000`)
- **Config:** custom markers registered in `pytest.ini` (`order`, `security`, `perf`)
- **Data:** tests are **seed-independent** (they create users when needed); seeded accounts are used opportunistically if `seed_data.py` was executed.

---

## 4. Test Metrics

### Automated execution summary (provided run)
- **Total tests collected:** 66  
- **Result:** **53 passed, 4 failed, 9 xfailed**

### Fail analysis
All **4 FAILs** share one root cause: **`/users/search` is broken (BUG-006)**.  
One test intended as a **BUG-007 sentinel** is currently **blocked** because the route never reaches `search_users()`.

### About XFAILs (defect sentinels)
XFAILs in `test_api.py` are intentional **defect sentinels**. They should remain XFAIL only while the bug exists; once the related defect is resolved, the XFAIL should be converted back to a normal assertion so that CI reflects a clean and reliable signal.

---

## 5. Coverage and Traceability (high level)

### Endpoint coverage (automation)
- `/` and `/health`: smoke + schema sanity
- `/users`: create/list/read + validation + pagination/sorting + rate-limit signal
- `/login` and `/logout`: token format, invalid creds, logout semantics
- `/users/{id}` (PUT): auth required, invalid token, validation, session signals
- `/users/{id}` (DELETE): Basic auth, negative scenarios, authorization bypass signal
- `/users/search`: functional + input-hardening tests (**currently blocked by BUG-006**)
- `/stats`: schema + disclosure sentinel
- Hidden runtime endpoint `/users/bulk`: reachability + response-shape check (also documented as a contract gap)

---

## 6. Bug Summary

### Total bugs documented
- **23** issues were documented in `bugs_report.md` (BUG-001 … BUG-023).

### Bugs by severity
| Severity | Count |
|---|---:|
| Critical | 2 |
| High | 8 |
| Medium | 7 |
| Low | 6 |

### Bugs by category (normalized)
| Category | Count |
|---|---:|
| Security | 8 |
| Logic | 5 |
| Validation | 4 |
| Data Integrity | 3 |
| Authorization | 2 |
| API Semantics | 2 |
| Session Management | 2 |
| Reliability | 2 |
| Authentication | 2 |
| Documentation | 2 |
| Pagination | 1 |
| Functional | 1 |

### Priority bug list (what to fix first)
### Critical priority
- **BUG-006** — `/users/search` is broken due to route shadowing by `/users/{user_id}`
- **BUG-001** — Username case-collision can overwrite an existing user (data loss)

### High priority
- **BUG-008** — `/stats?include_details=true` leaks emails and active session tokens (unauthenticated)
- **BUG-011** — Password hashing is insecure (MD5 + static salt)
- **BUG-003** — Any authenticated user can update any other user (missing authorization)
- **BUG-005** — Any valid Basic-auth user can delete any other user (missing authorization)
- **BUG-009** — Session token is not bound to client IP (replay/hijack risk)
- **BUG-010** — Session expiry is not enforced (tokens do not expire)
- **BUG-017** — Hidden `/users/bulk` endpoint is unauthenticated and silently drops failures
- **BUG-002** — `/users` pagination returns `limit + 1` records (off-by-one)

### Medium priority
- **BUG-013** — No brute-force protection on `/login`
- **BUG-014** — `/login` timing differences allow username enumeration
- **BUG-015** — Duplicate phone numbers are allowed (missing uniqueness constraint)
- **BUG-016** — Phone validation is missing on update (invalid phones can be stored)
- **BUG-018** — Password policy is weak (length-only)
- **BUG-004** — Updating a soft-deleted user returns `200 OK` but silently does nothing
- **BUG-012** — Rate limiter is not thread-safe / not consistent under concurrency
- **BUG-007** — `/users/search` ignores `exact=true` for email search and applies inconsistent case handling

### Low priority
- **BUG-022** — OpenAPI contract gaps (schemas + hidden endpoints)
- **BUG-021** — Logout semantics are ambiguous (always 200 OK)
- **BUG-019** — `/health` “memory_*” fields are incorrect (string-length, not memory usage)
- **BUG-020** — Username allowlist is overly permissive (quotes/semicolon allowed)
- **BUG-023** — Sorting by `created_at` uses string conversion (fragile ordering implementation)

---

## 7. Notable Observations (implementation vs contract)

- The assignment documents `/users/search` as an additional endpoint, but it is effectively **non-functional** due to routing order (**BUG-006**).
- `/users/bulk` is callable at runtime but hidden from OpenAPI (`include_in_schema=False`), creating a **contract gap** (**BUG-017**, **BUG-022**).
- `/logout` always returns `200 OK` with ambiguous semantics (can mask client issues) (**BUG-021**).

---

## 8. Recommendations (Action Plan)

### Release-blocking fixes (must)
1. **Fix routing for `/users/search`** (BUG-006)  
   - Place `/users/search` above `/users/{user_id}`, or constrain the path parameter (e.g., `user_id: int`) to prevent shadowing.
2. **Prevent username case-collision overwrite** (BUG-001)  
   - Normalize username consistently for both duplicate checks and storage key (e.g., always compare/store lowercased).
3. **Lock down data exposure** (BUG-008)  
   - Protect `/stats` (admin-only) and **never** return session tokens; minimize PII.
4. **Fix authorization model** (BUG-003, BUG-005)  
   - Enforce ownership or roles for update/delete.
5. **Harden sessions** (BUG-009, BUG-010)  
   - Either enforce IP binding or remove IP storage (avoid false security); enforce expiry; consider rotation.
6. **Replace password hashing** (BUG-011)  
   - Use a slow password hash (Argon2id/bcrypt/scrypt) with per-user salt.
7. **Bulk endpoint safety** (BUG-017)  
   - Require auth, document it (or remove it), and return per-item results; do not swallow exceptions.
   - Specifically address silent rate-limit failures caused by hardcoded client IP during bulk processing.

### Recommended After Critical Fixes (should)
- Pagination correctness (`limit` off-by-one) (BUG-002)
- Phone uniqueness/validation alignment (BUG-015, BUG-016)
- Brute-force & timing hardening on `/login` (BUG-013, BUG-014)
- Thread-safe and deployment-safe rate limiter (BUG-012)

### Hygiene/quality (could)
- Correct misleading `/health` memory metrics (BUG-019)
- Review username allowlist policy (BUG-020)
- Improve OpenAPI schemas and response models (BUG-022)
- Replace fragile created_at string sort (BUG-023)

---

## 9. Security Assessment

### High-risk vulnerabilities
- **Token/PII disclosure:** `/stats?include_details=true` leaks **emails + active session tokens** (BUG-008)
- **Authorization bypass:** Any authenticated user can update any user (BUG-003); any Basic-auth user can delete any user (BUG-005)
- **Session weaknesses:** tokens not IP-bound (BUG-009) and expiry not enforced (BUG-010)
- **Weak password hashing:** MD5 + static salt (BUG-011)
- **Undocumented ingestion surface:** hidden unauthenticated bulk endpoint with silent drops (BUG-017)

### Recommended Improvements
- Apply proper access control: limit `/stats` to privileged users and add ownership checks for update and delete operations.
- Move away from MD5 and store passwords using a slow, purpose-built password hashing algorithm with per-user salts.
- Align session behavior with its contract by enforcing expiration and cleaning up stale tokens.
- Harden the authentication flow by adding rate limiting and minimizing observable timing differences on failed logins.
- Review and clean up the API surface so that documentation matches what is actually exposed at runtime.

---