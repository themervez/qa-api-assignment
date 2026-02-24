#  QA Engineer Assignment - User Management API

## Repository Setup Instructions

**Important:** You should create your own repository for this assignment.

1. **Clone this repository** to your local machine
2. **Create a new PUBLIC repository** on GitHub/GitLab under your account
3. **Push the code** to your new repository
4. **Work on your assignment** in your own repository
5. **Submit the link** to your PUBLIC repository when complete

Your submission repository should be PUBLIC so we can review your the assignment.

##  Mission Brief

You've been provided with a **User Management API** built with FastAPI. 

Your mission is to thoroughly test this API, identify bugs, and demonstrate your QA expertise.

##  Assignment Objectives

### Primary Goals
- 🔍 **Identify and document** all bugs in the API
-  **Write automated tests** using your preferred framework
-  **Create comprehensive reports** documenting your findings

##  API Endpoints Overview

###  Public Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | API root information |
| `POST` | `/users` | Create a new user |
| `GET` | `/users` | List all users (paginated) |
| `GET` | `/users/{user_id}` | Get specific user details |
| `POST` | `/login` | User authentication |
| `POST` | `/logout` | End user session |

###  Protected Endpoints (Authentication Required)
| Method | Endpoint | Description |
|--------|----------|-------------|
| `PUT` | `/users/{user_id}` | Update user information |
| `DELETE` | `/users/{user_id}` | Delete a user |

###  Additional Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/users/search?q={query}` | Search users |
| `GET` | `/stats` | System statistics |
| `GET` | `/health` | Health check |

##  Setup Instructions

### Prerequisites
```bash
# Ensure Python 3.10+ is installed
python3 --version
```

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Launch API Server
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Step 3: Seed Test Data
```bash
python3 seed_data.py
```

### Step 4: Verify Setup
- 📖 API Documentation: http://localhost:8000/docs
-  Alternative Docs: http://localhost:8000/redoc

##  Your Tasks

###  Task 1: Bug Identification

**Objective:** Identify and document **at least 10 bugs** in the API.

For each bug, provide:
- ** Bug ID:** Unique identifier (e.g., BUG-001)
- ** Description:** Clear explanation of the issue
- ** Steps to Reproduce:** Detailed reproduction steps
- ** Expected Behavior:** What should happen
- ** Actual Behavior:** What actually happens
- ** Severity:** Critical / High / Medium / Low
- ** Evidence:** Request/response examples

#### Bug Report Template
```markdown
## BUG-001: [Bug Title]
**Severity:** High
**Category:** Security/Logic/Performance/Validation

**Description:**
[Clear description of the bug]

**Steps to Reproduce:**
1. Step one
2. Step two
3. Step three

**Expected Result:**
[What should happen]

**Actual Result:**
[What actually happens]

**Evidence:**
```json
// Request/Response examples
```
```

###  Task 2: Test Implementation

**Objective:** Write comprehensive automated tests.

Your test suite should include:

#### Coverage Requirements
-  All API endpoints
-  Positive and negative scenarios
-  Edge cases and boundaries
-  Response schema validation
-  Authentication/authorization flows
-  Performance benchmarks
-  Concurrent request handling

#### Test Categories to Cover
```python
# Example test structure
class TestUserAPI:
    def test_user_creation()
    def test_duplicate_users()
    def test_authentication()
    def test_authorization()
    def test_input_validation()
    def test_edge_cases()
    def test_performance()
    def test_security_vulnerabilities()
```

###  Task 3: Test Report

**Objective:** Create a professional test report.

#### Required Sections

1. ** Executive Summary**
   - Testing overview
   - Key findings
   - Risk assessment

2. ** Test Metrics**
   - Total tests executed
   - Pass/fail ratio
   - Code coverage percentage
   - Performance metrics

3. ** Bug Summary**
   - Total bugs found
   - Bugs by severity
   - Bugs by category

4. ** Recommendations**
   - Priority fixes
   - Security improvements
   - Performance optimizations

5. ** Security Assessment**
   - Vulnerabilities identified
   - Risk levels
   - Mitigation suggestions

##  Deliverables

### Required Files
| File | Description |
|------|-------------|
| `test_api.py` | Your automated test suite |
| `bugs_report.md` | Detailed bug documentation |
| `test_report.md` | Comprehensive test report |
| `requirements_test.txt` | Test dependencies |
| `README_TESTS.md` | How to run your tests |

##  Submission Guidelines

### Submission Format

**Required:** Submit your PUBLIC GitHub/GitLab repository link containing:
- Your test implementation
- Bug reports
- Test documentation
- All deliverables listed above

** Best of luck!**