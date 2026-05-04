from __future__ import annotations

import firebase_admin
from firebase_admin import auth, credentials
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.config import get_setting

# Locally: set GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
_settings = get_setting()

if not firebase_admin._apps:
    firebase_admin.initialize_app(
        options={"projectId": _settings.firebase_project_id}
    )

#auto_error=False so we control the 401 message
_bearer = HTTPBearer(auto_error=False)

class FirebaseUser(BaseModel):
    """Verified claims extracted from the firebase id token"""
    uid: str
    email:str | None = None
    name: str | None = None

async def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),) -> FirebaseUser: 
    """
    FastAPI dependency.  Inject with:  user: FirebaseUser = Depends(get_current_user)
    Returns a FirebaseUser on success.
    Raises HTTP 401 on any verification failure.
    """

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    try:
        decode = auth.verify_id_token(credentials.credentials)
    except auth.ExpiredIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired — refresh and retry",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except auth.InvalidIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return FirebaseUser(
        uid=decode["uid"],
        email=decode.get("email"),
        name=decode.get("name")
    )