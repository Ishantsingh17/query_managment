"""Password hashing and signed session tokens (local/mock identity; swap for enterprise IdP later)."""
import hashlib
import hmac
import secrets

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import get_settings

_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS).hex()
    return f"pbkdf2${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS).hex()
    return hmac.compare_digest(candidate, digest)


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="aep-session")


def issue_token(user_id: str, remember: bool = False) -> str:
    return _serializer().dumps({"uid": user_id, "r": remember})


def read_token(token: str) -> str | None:
    """Returns the user id, or None if the token is invalid/expired."""
    settings = get_settings()
    try:
        data = _serializer().loads(token, max_age=settings.token_ttl_minutes * 60 * 30)
    except (BadSignature, SignatureExpired):
        return None
    # Non-remembered sessions use the standard TTL; remembered sessions get 30x.
    if not data.get("r"):
        try:
            _serializer().loads(token, max_age=settings.token_ttl_minutes * 60)
        except SignatureExpired:
            return None
    return data.get("uid")
