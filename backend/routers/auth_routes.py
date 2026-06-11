"""auth_routes.py — PIN 登入端點"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .. import auth

router = APIRouter(prefix="/api/auth")


class LoginBody(BaseModel):
    pin: str


@router.post("/login")
def login(body: LoginBody):
    return {"token": auth.login_with_pin(body.pin)}
