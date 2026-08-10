"""
APOLLO-M Authentication Module
JWT-based login with role-based access control.

Roles:
    admin  — full access, can trigger analysis
    analyst — read-only access to all endpoints
    viewer  — limited access (summary + alerts only)
"""

from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel

# ── Config ─────────────────────────────────────────────────────
SECRET_KEY = "apollo-m-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# ── Password hashing ───────────────────────────────────────────
import hashlib

def simple_hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def simple_verify(plain: str, hashed: str) -> bool:
    return simple_hash(plain) == hashed

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

# ── Demo users (replace with DB in production) ─────────────────
USERS_DB = {
    "admin": {
        "username": "admin",
        "hashed_password": simple_hash("apollo_admin"),
        "role": "admin",
        "full_name": "APOLLO Admin"
    },
    "analyst": {
        "username": "analyst",
        "hashed_password": simple_hash("apollo_analyst"),
        "role": "analyst",
        "full_name": "APOLLO Analyst"
    },
    "viewer": {
        "username": "viewer",
        "hashed_password": simple_hash("apollo_viewer"),
        "role": "viewer",
        "full_name": "APOLLO Viewer"
    }
}

# ── Pydantic models ────────────────────────────────────────────
class Token(BaseModel):
    access_token: str
    token_type: str
    role: str
    expires_in: int

class TokenData(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = None

class User(BaseModel):
    username: str
    role: str
    full_name: str

# ── Auth functions ─────────────────────────────────────────────
def verify_password(plain: str, hashed: str) -> bool:
    return simple_verify(plain, hashed)

def get_user(username: str) -> Optional[dict]:
    return USERS_DB.get(username)

def authenticate_user(username: str, password: str) -> Optional[dict]:
    user = get_user(username)
    if not user:
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    return user

def create_access_token(data: dict,
                        expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username, role=role)
    except JWTError:
        raise credentials_exception

    user = get_user(token_data.username)
    if user is None:
        raise credentials_exception
    return User(
        username=user["username"],
        role=user["role"],
        full_name=user["full_name"]
    )

def require_role(*roles: str):
    """Dependency that enforces role-based access."""
    async def role_checker(
        current_user: User = Depends(get_current_user)
    ) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role: {roles}"
            )
        return current_user
    return role_checker