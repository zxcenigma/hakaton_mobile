import jwt
from passlib.context import CryptContext

from typing import Any
from datetime import timedelta, timezone, datetime

from monoapi.core import settings

import bcrypt
# Хук
if not hasattr(bcrypt, "__about__"):
    bcrypt.__about__ = type("X", (), {"__version__": "4.3.0"})

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain, hashed) -> bool:
    return pwd_context.verify(plain, hashed)


def encode_jwt(payload: dict, 
               private_key: str = settings.auth_jwt.private_key_path.read_text(), 
               algorithm: str = settings.auth_jwt.jwt_algorithm,
               expire_days: int = settings.auth_jwt.jwt_available_days,
               expire_timedelta: timedelta | None = None,):
    to_encode = payload.copy()

    now = datetime.now(timezone.utc)
    #access
    if expire_timedelta:
        expire = now + expire_timedelta
    #refresh
    else:
        expire = now + timedelta(days=float(expire_days))
    
    to_encode.update(
        exp=expire,
        iat=now,
    )
    encoded = jwt.encode(to_encode, private_key, algorithm)
    return encoded


def decode_jwt(token: str | bytes, 
                public_key: str = settings.auth_jwt.public_key_path.read_text(), 
                algorithm: str = settings.auth_jwt.jwt_algorithm) -> dict[str, Any]:
    
    decoded_token = jwt.decode(token, public_key, algorithms=[algorithm])
    return decoded_token
