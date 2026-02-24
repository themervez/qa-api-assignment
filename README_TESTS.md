# README_TESTS.md — User Management API (v1.0.0)

- You will find in this document how to run the **automated test suite** (`test_api.py`), how the suite is structured, and how to interpret results (PASS/FAIL/XFAIL).     
- It also points to the supporting QA artifacts: bugs_report.md (reproducible defects) and test_report.md (risk summary and metrics).
---

## 1) What is included (as deliverables)

- **`test_api.py`** — end-to-end API tests (functional + negative + edge + auth + perf/concurrency + security signals)
- **`bugs_report.md`** — detailed bug reports with reproduction steps and evidence
- **`test_report.md`** — executive summary + risk assessment + test metrics narrative
- **`pytest.ini`** — registers custom markers (`security`, `perf`, `order`)
- **`requirements_test.txt`** — test dependencies
- **`README_TESTS.md`** — this file (how to run the tests)

---

## 2) Quick start

### Prerequisites
- Python **3.10+**
- A running API instance (FastAPI)

### Install dependencies
```bash
pip install -r requirements.txt
pip install -r requirements_test.txt
```

### Start the API
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

(Optional) Seed sample users:
```bash
python3 seed_data.py
```

### Run the full test suite
```bash
pytest -q
```

### Common useful runs
Run with output + shorter tracebacks:
```bash
pytest -q -rA --tb=short
```

Run *only* fast/core checks (skip perf & security):
```bash
pytest -q -m "not perf and not security"
```

Run perf checks only:
```bash
pytest -q -m perf
```

Run security checks only:
```bash
pytest -q -m security
```

---

## 3) Configuration (env vars)

The suite is designed to run against any reachable instance of the API.

| Variable | Default | Purpose |
|---|---:|---|
| `BASE_URL` | `http://127.0.0.1:8000` | Where the API is running |

Example:
```bash
BASE_URL="http://localhost:8000" pytest -q
```
---

## 4) Suite design principles

### a) “Self-contained” by default
The suite does **not require** `seed_data.py`. When needed, tests create their own users with randomized usernames/emails to avoid collisions and to keep runs reproducible.

### b) Stable rate-limit behavior
`POST /users` is rate-limited **per client IP** in this API.  
To avoid flaky tests in shared reviewer environments, request helpers attach a default **TEST-NET IP** header (unless you explicitly override it).

### c) Clear separation of concerns
- **Helpers** encapsulate request building, auth headers, and common assertions.
- Tests focus on **behavior** (status codes, schemas, invariants, and security expectations).
- Heavier tests are tagged with markers so they can be excluded from CI if desired.

### d) Ordered narrative (without hard dependency)
Tests are annotated with `@pytest.mark.order(N)` to read like a story (setup → core flows → negative/edge → security/perf).  
If `pytest-order` is missing, tests still run—only ordering is not enforced.

---

## 5) Coverage overview

The suite targets the assignment’s required categories:

### Endpoint coverage (per assignment)
- `GET /` — root info
- `POST /users` — create user
- `GET /users` — list users (pagination)
- `GET /users/{id}` — get user details
- `PUT /users/{id}` — update user (auth)
- `DELETE /users/{id}` — delete user (auth)
- `POST /login` — authentication
- `POST /logout` — session invalidation
- `GET /users/search?q=...` — search (note: currently blocked by a routing issue; see Known Issues)
- `GET /stats` — system stats (+ information disclosure checks)
- `GET /health` — health check

### Test categories
- ✅ Positive flows (happy path)
- ✅ Negative flows (invalid credentials, invalid inputs, missing fields)
- ✅ Edge cases / boundaries (pagination bounds, empty/too-long inputs, unicode/format validation)
- ✅ Schema/shape validation (response keys, types, and invariants where the API is inconsistent)
- ✅ Auth & session flows (login/logout, session header usage)
- ✅ Security signals (information disclosure, auth bypass, brute-force / timing hints)
- ✅ Performance & concurrency (basic budgets + multi-thread bursts)

---

## 6) How to interpret results (PASS / FAIL / XFAIL)

### PASS
The API behavior matched the test expectation.

### FAIL
A regression was detected or an API behavior violated a hard requirement (e.g., basic contract, auth rule, or critical invariant).

### XFAIL (Expected failure)
Some tests intentionally use `pytest.xfail(...)` as **bug sentinels**.  
These represent **confirmed issues** documented in `bugs_report.md`. The intent is:

- If the bug is still present → test is marked **XFAIL** (suite stays informative, not noisy)
- If the bug is fixed → the test will **PASS** automatically (visible progress)

#### Bug sentinel IDs referenced in the suite
Current XFAIL sentinels map to:
`BUG-001`, `BUG-002`, `BUG-003`, `BUG-005`, `BUG-007`, `BUG-008`, `BUG-009`, `BUG-013`, `BUG-014`, `BUG-015`, `BUG-023`.

> Tip for reviewers: an unexpected **XPASS** is a good sign—meaning the API likely improved compared to the documented bug state.

---

## 7) Known issues that affect testability

A few API defects impact what can be tested “cleanly” without changing the server:

- **`GET /users/search` is unreachable (route shadowing)** — the documented endpoint returns **400** before hitting the search handler (**BUG-006**).  
  Tests cover the observed behavior and document the defect; once fixed, deeper search correctness tests can be expanded.

- **Hidden/undocumented behavior** — some behaviors exist at runtime but are missing or inconsistent in the published schema/docs.  
  The suite favors **runtime truth** while still noting spec mismatches in `bugs_report.md`.

---

## 8) Optional:

These are not required to run the suite, but they help in quickly assessing the results.

Generate a JUnit report
```bash
pytest -q --junitxml=pytest-results.xml
```

Run with verbose output for debugging:
```bash
pytest -vv -rA --tb=long
```
---

## 9) Troubleshooting

### “Connection refused” / timeouts
- Confirm the API is running and `BASE_URL` matches the host/port.
- Check that nothing else is bound to port `8000`.

### Flaky create-user tests / unexpected 429
- This API rate-limits create requests per client IP.
- The suite uses a default TEST-NET IP; avoid running multiple instances concurrently against the same server.

### Marker warnings
If you see warnings like “unknown marker”, ensure you’re using the included `pytest.ini` and that you’re running pytest from the repository root.

### 401 Unauthorized for valid credentials
If you get **401 Unauthorized** even though you believe the credentials are correct, it usually means the API has **no users loaded** (or you're using credentials that were never seeded).

**What to do:**  
Seed the test data (recommended for manual testing and for using the sample accounts mentioned in docs):
```bash
  python3 seed_data.py
 ```
---

## 10) Notes for maintainers

- When fixing a bug, prefer to **remove the corresponding XFAIL** only after verifying `bugs_report.md` is updated (or let the XPASS signal guide the change).
- If you tighten validation rules, update both the OpenAPI schema and the error-message contract to keep tests stable and user-facing behavior predictable.
