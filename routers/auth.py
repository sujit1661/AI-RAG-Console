from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from typing import Optional
import re
import logging

from backend.auth import (
    verify_session, delete_session, create_session,
    get_current_user, create_user, get_user_info, login_user,
    load_users, save_users, hash_password, verify_password,
    SECURE_COOKIES,
)
from backend.deps import get_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str = ""

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


def _set_session_cookie(response: Response, token: str):
    response.set_cookie(
        key="session_token", value=token,
        httponly=True,
        secure=SECURE_COOKIES,   # True in production (HTTPS), False in local dev
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
    )


@router.get("/check")
async def check_auth(token: Optional[str] = Depends(get_token)):
    username = verify_session(token)
    return {"authenticated": bool(username), "username": username}


@router.post("/login")
async def login(request: Request, data: LoginRequest, response: Response):
    try:
        result = login_user(data.username, data.password)
        _set_session_cookie(response, result["token"])
        logger.info(f"User {data.username} logged in via {result.get('source')}")
        return {"success": True, "token": result["token"],
                "refresh_token": result.get("refresh_token"),
                "username": data.username, "user_info": get_user_info(data.username) or {}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/register")
async def register(request: Request, data: RegisterRequest, response: Response):
    if not data.username or len(data.username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    if not re.match(r'^[a-zA-Z0-9_]+$', data.username):
        raise HTTPException(status_code=400, detail="Username: letters, numbers, underscores only")
    if not data.password or len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    try:
        if create_user(data.username, data.password, data.email):
            token = create_session(data.username)
            _set_session_cookie(response, token)
            logger.info(f"New user {data.username} registered")
            return {"success": True, "token": token, "username": data.username,
                    "user_info": get_user_info(data.username)}
        raise HTTPException(status_code=400, detail="Username already exists")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user")
async def get_user(token: Optional[str] = Depends(get_token)):
    username = verify_session(token)
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"username": username, "user_info": get_user_info(username)}


@router.post("/change-password")
async def change_password(data: ChangePasswordRequest, token: Optional[str] = Depends(get_token)):
    username = get_current_user(token)
    users = load_users()
    if username not in users:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(data.old_password, users[username]["password_hash"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    users[username]["password_hash"] = hash_password(data.new_password)
    save_users(users)
    return {"success": True}


@router.post("/logout")
async def logout(response: Response, token: Optional[str] = Depends(get_token)):
    if token:
        delete_session(token)
    response.delete_cookie(key="session_token")
    return {"success": True}


@router.post("/refresh")
async def refresh_token(request: Request, response: Response):
    body = await request.json()
    refresh_tok = body.get("refresh_token", "")
    if not refresh_tok:
        raise HTTPException(status_code=400, detail="refresh_token required")
    try:
        from backend.supabase_config import get_supabase
        res = get_supabase().auth.refresh_session(refresh_tok)
        if not res.session:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        _set_session_cookie(response, res.session.access_token)
        return {"success": True, "token": res.session.access_token,
                "refresh_token": res.session.refresh_token}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Token refresh failed")
