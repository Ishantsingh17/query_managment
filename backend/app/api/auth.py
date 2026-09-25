"""Common sign-in for all roles, with a backend-validated post-login redirect (`next`)."""
import re

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, user_view
from app.core.errors import AppError, AuthError
from app.core.labels import ROLE_LABELS
from app.core.security import issue_token, verify_password
from app.db.models import RequestRecord, User
from app.db.session import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])

HOME = {"AUDITOR": "/dashboard", "VALIDATOR": "/queue", "SME": "/approvals"}
_RID = r"(?P<rid>AUD-\d{4}-\d+)"
_COMMON = [r"/completed", r"/reports", r"/settings", r"/help"]
# Destinations each role may be redirected to after sign-in (the API enforces access again on every call).
ROUTES = {
    # /requests/{rid} (the auditor's own request detail) is deliberately AUDITOR-only here: it is the
    # auditor's actionable page, ownership-checked below. A validator/SME arriving via a stale or
    # generic next-link must land on their own actionable page instead (queue / approvals), not this
    # read-only auditor view — see resolve_next's wrong_role fallback, which already handles this
    # correctly for every other cross-role route.
    "AUDITOR": [r"/dashboard", r"/requests", r"/requests/new", rf"/requests/{_RID}", rf"/requests/{_RID}/(package|final)"],
    "VALIDATOR": [r"/queue", rf"/queue/{_RID}", rf"/validation/requests/{_RID}", r"/requests"],
    "SME": [r"/dashboard", r"/approvals", rf"/approvals/{_RID}", rf"/approvals/requests/{_RID}", r"/requests"],
}


def _match(role: str, path: str):
    for pattern in ROUTES.get(role, []) + _COMMON:
        m = re.fullmatch(pattern, path)
        if m:
            return m
    return None


def resolve_next(db: Session, user: User, next_path: str | None) -> dict:
    """Validate a post-login destination for this user. Never trusts the frontend."""
    home = HOME.get(user.role, "/")
    if not next_path:
        return {"allowed": True, "redirect": home, "reason": None}
    path = next_path.split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/") or path.startswith("//") or "\\" in path or ":" in path:
        return {"allowed": False, "redirect": home, "reason": "invalid"}
    m = _match(user.role, path)
    if m is None:
        needed = [ROLE_LABELS[r] for r in ROUTES if r != user.role and _match(r, path)]
        return {"allowed": False, "redirect": home, "reason": "wrong_role",
                "required_role": needed[0] if needed else None}
    rid = m.groupdict().get("rid")
    if rid:
        r = db.get(RequestRecord, rid)
        if r is None:
            return {"allowed": False, "redirect": home, "reason": "not_found"}
        if user.role == "AUDITOR" and r.auditor_id != user.user_id:
            return {"allowed": False, "redirect": home, "reason": "not_permitted"}
        if re.search(r"/(package|final)$", path) and not r.final_response_path:
            return {"allowed": True, "redirect": f"/requests/{rid}", "reason": "package_not_ready"}
    return {"allowed": True, "redirect": path, "reason": None}


class LoginBody(BaseModel):
    email: str
    password: str
    remember: bool = False
    next: str | None = None


@router.post("/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.strip().lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise AuthError("Incorrect email or password. Please try again.", code="invalid_credentials")
    return {"token": issue_token(user.user_id, body.remember), "user": user_view(user),
            "redirect": resolve_next(db, user, body.next)}


@router.get("/resolve-next")
def resolve(next: str | None = Query(None), db: Session = Depends(get_db), user: User = Depends(current_user)):
    return resolve_next(db, user, next)


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_view(user)


@router.post("/sso")
def sso():
    raise AppError("Enterprise SSO is not configured in this environment. Sign in with your corporate email.",
                   code="sso_not_configured", status_code=501)
