"""Auth and role-based authorization — enforced in the backend, never by the LLM."""
from collections.abc import Callable

from fastapi import Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.errors import AuthError, ForbiddenError
from app.core.security import read_token
from app.db.models import User
from app.db.session import get_db


def current_user(request: Request, db: Session = Depends(get_db), token: str | None = Query(None)) -> User:
    header = request.headers.get("Authorization", "")
    raw = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else token
    if not raw:
        raise AuthError("Please sign in to continue.")
    uid = read_token(raw)
    user = db.get(User, uid) if uid else None
    if user is None:
        raise AuthError("Session expired. Please sign in again to continue.", code="session_expired")
    return user


def require_role(*roles: str) -> Callable[..., User]:
    def _dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise ForbiddenError("You do not have access to this action.")
        return user
    return _dep


def user_view(u: User) -> dict:
    initials = "".join(p[0] for p in u.full_name.split()[:2]).upper()
    return {"user_id": u.user_id, "email": u.email, "full_name": u.full_name, "first_name": u.full_name.split()[0],
            "role": u.role, "title": u.title, "initials": initials}
