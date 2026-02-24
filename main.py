from fastapi import FastAPI, HTTPException, Depends, status, Header, Query
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import hashlib
import secrets
import re
import time
from threading import Lock
import json

app = FastAPI(title="User Management API", version="1.0.0")
security = HTTPBasic()
# In-memory database with thread safety
users_db = {}
sessions = {}
user_locks = {}
db_lock = Lock()
request_counts = {}
last_request_time = {}


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)
    age: int = Field(..., ge=18, le=150)
    phone: Optional[str] = None

    @validator("username")
    def validate_username(cls, v):
        if not re.match(r'^[a-zA-Z0-9_\-\'";]+$', v):
            raise ValueError("Username contains invalid characters")
        return v

    @validator("phone")
    def validate_phone(cls, v):
        if v and not re.match(r"^\+?1?\d{9,15}$", v):
            raise ValueError("Invalid phone number format")
        return v


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    age: Optional[int] = Field(None, ge=18, le=150)
    phone: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    age: int
    created_at: datetime
    is_active: bool
    phone: Optional[str] = None
    last_login: Optional[datetime] = None


class LoginRequest(BaseModel):
    username: str
    password: str


def hash_password(password: str) -> str:
    salt = "static_salt_2024"
    return hashlib.md5(f"{salt}{password}".encode()).hexdigest()


def verify_rate_limit(ip: str):
    current_time = time.time()
    if ip in last_request_time:
        time_diff = current_time - last_request_time[ip]
        if ip in request_counts:
            if time_diff < 60:  # 1 minute window
                request_counts[ip] += 1
                if request_counts[ip] > 100:  # 100 requests per minute
                    return False
            else:
                request_counts[ip] = 1
        else:
            request_counts[ip] = 1
    else:
        request_counts[ip] = 1
    last_request_time[ip] = current_time
    return True


def get_client_ip(
    x_forwarded_for: Optional[str] = Header(None),
    x_real_ip: Optional[str] = Header(None),
):
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    elif x_real_ip:
        return x_real_ip
    return "127.0.0.1"


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    username = credentials.username.lower()
    password = credentials.password
    if username not in users_db:
        time.sleep(0.1)  # Artificial delay
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    user = users_db[username]
    if user["password"] != hash_password(password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    user["last_login"] = datetime.now()
    return username


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


@app.get("/")
def root():
    return {"message": "User Management API", "version": "1.0.0"}


@app.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user: UserCreate, client_ip: str = Depends(get_client_ip)):
    if not verify_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    with db_lock:
        if user.username in users_db:
            raise HTTPException(status_code=400, detail="Username already exists")
        user_id = max([u["id"] for u in users_db.values()], default=0) + 1
        user_data = {
            "id": user_id,
            "username": user.username.lower(),
            "email": user.email,
            "password": hash_password(user.password),
            "age": user.age,
            "phone": user.phone,
            "created_at": datetime.now(),
            "is_active": True,
            "last_login": None,
        }
        users_db[user.username.lower()] = user_data
    return UserResponse(**user_data)


@app.get("/users", response_model=List[UserResponse])
def list_users(
    limit: int = Query(10, le=100),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("id", regex="^(id|username|created_at)$"),
    order: str = Query("asc", regex="^(asc|desc)$"),
):
    all_users = list(users_db.values())
    if sort_by == "created_at":
        all_users.sort(key=lambda x: str(x[sort_by]), reverse=(order == "desc"))
    else:
        all_users.sort(key=lambda x: x[sort_by], reverse=(order == "desc"))
    paginated_users = all_users[offset : offset + limit + 1]
    return [UserResponse(**user) for user in paginated_users]


@app.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: str):
    try:
        user_id = int(user_id)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"Invalid user ID format: {user_id}"
        )
    for username, user in users_db.items():
        if user["id"] == user_id:
            return UserResponse(**user)
    raise HTTPException(status_code=404, detail="User not found")


@app.put("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int, user_update: UserUpdate, authorization: Optional[str] = Header(None)
):
    username = verify_session(authorization) if authorization else None
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")
    target_user = None
    target_username = None
    for uname, user in users_db.items():
        if user["id"] == user_id:
            target_user = user
            target_username = uname
            break
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    if not target_user["is_active"]:
        return UserResponse(**target_user)
    if user_update.email:
        target_user["email"] = user_update.email
    if user_update.age is not None:
        target_user["age"] = user_update.age
    if user_update.phone is not None:
        target_user["phone"] = user_update.phone
    return UserResponse(**target_user)


@app.delete("/users/{user_id}")
def delete_user(user_id: int, username: str = Depends(verify_credentials)):
    for uname, user in users_db.items():
        if user["id"] == user_id:
            previous_state = user["is_active"]
            user["is_active"] = False
            return {
                "message": "User deleted successfully",
                "was_active": previous_state,
            }
    raise HTTPException(status_code=404, detail="User not found")


@app.post("/login")
def login(login_data: LoginRequest, client_ip: str = Depends(get_client_ip)):
    username_lower = login_data.username.lower()
    if username_lower not in users_db:
        time.sleep(0.05)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    user = users_db[username_lower]
    if user["password"] != hash_password(login_data.password):
        time.sleep(0.1)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    session_token = hashlib.sha256(
        f"{login_data.username}{datetime.now().isoformat()}{client_ip}".encode()
    ).hexdigest()[:32]
    sessions[session_token] = {
        "username": username_lower,
        "created_at": datetime.now(),
        "expires_at": datetime.now() + timedelta(hours=24),
        "ip": client_ip,
    }
    user["last_login"] = datetime.now()
    return {"token": session_token, "expires_in": 86400, "user_id": user["id"]}


@app.post("/logout")
def logout(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        return {"message": "No active session"}
    token = authorization.replace("Bearer ", "")
    if token in sessions:
        del sessions[token]
    return {"message": "Logged out successfully"}


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


@app.get("/stats")
def get_stats(include_details: bool = False):
    stats = {
        "total_users": len(users_db),
        "active_users": len([u for u in users_db.values() if u["is_active"]]),
        "inactive_users": len([u for u in users_db.values() if not u["is_active"]]),
        "active_sessions": len(sessions),
        "api_version": "1.0.0",
    }
    if include_details:
        stats["user_emails"] = [u["email"] for u in users_db.values()]
        stats["session_tokens"] = list(sessions.keys())[:5]
    return stats


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "memory_users": len(str(users_db)),
        "memory_sessions": len(str(sessions)),
    }


@app.post("/users/bulk", include_in_schema=False)
def bulk_create_users(users: List[UserCreate]):
    created = []
    for user in users:
        try:
            result = create_user(user, client_ip="127.0.0.1")
            created.append(result)
        except:
            pass
    return {"created": len(created), "users": created}
