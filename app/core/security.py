import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: uuid.UUID, school_id: uuid.UUID, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "school_id": str(school_id),
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    Returns the decoded payload or raises JWTError if invalid/expired.
    Callers (deps.py) are responsible for catching JWTError and raising HTTPException.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def generate_refresh_token() -> str:
    """Opaque, high-entropy token handed to the client. Never stored raw — see hash_refresh_token."""
    return secrets.token_urlsafe(64)


def hash_refresh_token(token: str) -> str:
    """
    SHA-256 (not bcrypt): the token is already high-entropy random data, not a
    human password, so a fast deterministic hash is enough to let us look it
    up by exact value in the DB without ever storing it in cleartext.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def refresh_token_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
