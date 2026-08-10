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
# The signing key MUST come from the environment. It was previously the literal
# "apollo-m-secret-key-change-in-production" committed to the repository — with a
# public repo and a deployed API, anyone who read this file could mint themselves
# a valid admin token, because that is all an HS256 signature requires.
#
# In production a missing key is a hard failure rather than a warning: falling
# back to a default would silently restore the same vulnerability.
import logging
import os
import secrets as _secrets

log = logging.getLogger("APOLLO-M.auth")

_ENV = os.getenv("ENVIRONMENT", "development").lower()
SECRET_KEY = os.getenv("JWT_SECRET", "").strip()
if not SECRET_KEY:
    if _ENV in ("production", "prod"):
        raise RuntimeError(
            "JWT_SECRET is not set. Refusing to start in production with a "
            "predictable signing key — set it in the host's environment."
        )
    # Ephemeral per-process key for local development. Tokens do not survive a
    # restart, which is the correct trade: no shared default ever ships.
    SECRET_KEY = _secrets.token_urlsafe(48)
    log.warning("JWT_SECRET unset — generated an ephemeral development key; "
                "tokens will be invalidated on restart")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# ── Password hashing ───────────────────────────────────────────
# PBKDF2-HMAC-SHA256 via passlib, which is already a dependency and needs no
# native backend. The previous implementation was a bare, unsalted SHA-256:
# fast to brute-force and identical for identical passwords across accounts,
# which is precisely what a password KDF exists to prevent.
from passlib.hash import pbkdf2_sha256


def simple_hash(password: str) -> str:
    """Kept under the original name so existing call sites keep working."""
    return pbkdf2_sha256.hash(password)


def simple_verify(plain: str, hashed: str) -> bool:
    try:
        return pbkdf2_sha256.verify(plain, hashed)
    except (ValueError, TypeError):
        return False

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

# ── Demo users (replace with a DB-backed store for real use) ───
# The defaults are documented demo credentials, so they are public by design —
# but they are overridable from the environment, which is what makes a deployed
# instance defensible. Set APOLLO_ADMIN_PASSWORD (etc.) on the host and the
# published values stop granting access.
USERS_DB = {
    "admin": {
        "username": "admin",
        "hashed_password": simple_hash(
            os.getenv("APOLLO_ADMIN_PASSWORD", "apollo_admin")),
        "role": "admin",
        "full_name": "APOLLO Admin"
    },
    "analyst": {
        "username": "analyst",
        "hashed_password": simple_hash(
            os.getenv("APOLLO_ANALYST_PASSWORD", "apollo_analyst")),
        "role": "analyst",
        "full_name": "APOLLO Analyst"
    },
    "viewer": {
        "username": "viewer",
        "hashed_password": simple_hash(
            os.getenv("APOLLO_VIEWER_PASSWORD", "apollo_viewer")),
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