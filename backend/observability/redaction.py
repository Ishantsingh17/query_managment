"""Central, reusable redaction layer.

Applied to every event *before* it reaches any sink (local file or LangSmith), and installed as the LangSmith
client's `hide_inputs` / `hide_outputs` hooks so framework-generated runs (LangChain/LangGraph) are masked too.

Three mechanisms, in order:
  1. Key-based: values under sensitive keys (password, api_key, authorization, cookie, ...) are replaced wholesale.
  2. Known-secret values: exact values of secret-looking environment variables and of any value registered via
     `register_secret()` are replaced wherever they appear inside strings.
  3. Pattern-based: bearer tokens, `Authorization:` headers, well-known API key formats, JWTs, e-mail addresses,
     `password=...` pairs, plus optional financial identifiers and organization-defined regexes.

Credential masking (1, 2 and the built-in credential patterns) is ALWAYS on. `OBSERVABILITY_REDACTION_ENABLED=false`
only disables the optional rules (e-mail addresses, financial identifiers, organization-defined patterns).

Extend it with `OBSERVABILITY_REDACT_FIELDS` / `OBSERVABILITY_REDACT_PATTERNS`, or programmatically with
`add_field()` / `add_pattern()` / `register_secret()`.
"""
import os
import re
import threading
from collections.abc import Iterable, Mapping
from typing import Any

REDACTED = "[REDACTED]"
REDACTED_EMAIL = "[REDACTED_EMAIL]"

# Normalized (lower-case, '-'/' ' -> '_') key names whose values are always masked.
DEFAULT_SENSITIVE_KEYS = frozenset({
    "password", "passwd", "pwd", "secret", "client_secret", "api_key", "apikey", "x_api_key", "access_key",
    "secret_key", "private_key", "authorization", "proxy_authorization", "auth", "cookie", "set_cookie",
    "token", "access_token", "refresh_token", "id_token", "auth_token", "bearer", "session", "session_id",
    "sessionid", "credentials", "credential", "app_password", "connection_string", "dsn", "signature",
})
# Suffix/infix rules for keys such as `gmail_app_password`, `langsmith_api_key`, `db_password`, `x-auth-token`.
# `_tokens` (plural, e.g. `input_tokens`) is intentionally NOT sensitive.
_SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|secret|api_?key|access_?key|private_?key|credential|authorization|cookie|(^|_)token$|_token_|"
    r"(^|_)auth_?token|session_?id)",
)
FINANCIAL_KEYS = frozenset({
    "account_number", "bank_account", "bank_account_number", "iban", "swift", "bic", "routing_number",
    "sort_code", "card_number", "pan", "payment_reference", "utr", "utr_number",
})

_BUILTIN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Authorization / Proxy-Authorization headers rendered as text: keep the header name only.
    (re.compile(r"(?i)\b((?:proxy-)?authorization)\s*[:=]\s*[^\r\n,;]+"), r"\1: " + REDACTED),
    (re.compile(r"(?i)\b(cookie|set-cookie)\s*[:=]\s*[^\r\n]+"), r"\1: " + REDACTED),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{6,}"), "Bearer " + REDACTED),
    (re.compile(r"(?i)\bbasic\s+[A-Za-z0-9+/=]{8,}"), "Basic " + REDACTED),
    # key=value / key: value pairs with sensitive names (query strings, DSNs, config dumps)
    (re.compile(r"(?i)\b([\w-]*(?:password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret)"
                r"[\w-]*)(\"?\s*[:=]\s*\"?)([^\s\"'&,;}]+)"), r"\1\2" + REDACTED),
    # credentials embedded in URLs: scheme://user:pass@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s:/@]+):([^\s@/]+)@"), r"\1:" + REDACTED + "@"),
    # well-known key formats
    (re.compile(r"\b(?:sk|pk|rk)-(?:proj-|ant-|live-|test-)?[A-Za-z0-9_-]{16,}"), REDACTED),   # OpenAI / Anthropic / Stripe
    (re.compile(r"\bgsk_[A-Za-z0-9]{20,}"), REDACTED),                                     # Groq
    (re.compile(r"\blsv2_(?:pt|sk)_[A-Za-z0-9_]{20,}"), REDACTED),                          # LangSmith
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), REDACTED),                                # GitHub
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), REDACTED),                              # Slack
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED),                                       # AWS access key id
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), REDACTED),                                    # Google API key
    (re.compile(r"\bya29\.[0-9A-Za-z_-]{20,}"), REDACTED),                                  # Google OAuth access token
    (re.compile(r"\b1//[0-9A-Za-z_-]{30,}"), REDACTED),                                     # Google OAuth refresh token
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), REDACTED),  # JWT
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"), REDACTED),
]
_EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_FINANCIAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b"), REDACTED),  # IBAN
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), REDACTED),                                     # card / long account numbers
]
# Environment variable names whose *values* are treated as secrets.
_SECRET_ENV_NAME_RE = re.compile(r"(?i)(key|secret|token|password|passwd|credential|auth|cookie|dsn|private)")
_MIN_SECRET_LEN = 6


def _norm_key(key: Any) -> str:
    return re.sub(r"[\s\-.]+", "_", str(key).strip().lower())


class Redactor:
    """Thread-safe, reusable masker for nested JSON-like structures and free text."""

    def __init__(self, *, enabled: bool = True, redact_emails: bool = True, redact_financial: bool = False,
                 extra_fields: Iterable[str] = (), extra_patterns: Iterable[str] = (),
                 secrets: Iterable[str] = (), scan_environment: bool = True, max_depth: int = 20):
        self.enabled = enabled
        self.redact_emails = redact_emails
        self.max_depth = max_depth
        self._lock = threading.Lock()
        self._keys = set(DEFAULT_SENSITIVE_KEYS) | ({*FINANCIAL_KEYS} if redact_financial else set())
        self._keys |= {_norm_key(f) for f in extra_fields if str(f).strip()}
        self._credential_patterns = list(_BUILTIN_PATTERNS)
        self._patterns: list[tuple[re.Pattern[str], str]] = list(_FINANCIAL_PATTERNS) if redact_financial else []
        for p in extra_patterns:
            self.add_pattern(p)
        self._secrets: set[str] = set()
        self._secret_re: re.Pattern[str] | None = None
        if scan_environment:
            self.register_secrets(v for k, v in os.environ.items() if _SECRET_ENV_NAME_RE.search(k))
        self.register_secrets(secrets)

    # ---- configuration ------------------------------------------------------------------------
    def add_field(self, name: str) -> None:
        """Mask the value of every key with this (normalized) name."""
        with self._lock:
            self._keys.add(_norm_key(name))

    def add_pattern(self, pattern: str | re.Pattern[str], replacement: str = REDACTED) -> None:
        """Mask every match of an organization-defined regex."""
        compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
        with self._lock:
            self._patterns.append((compiled, replacement))

    def register_secret(self, value: str | None) -> None:
        """Mask this exact value wherever it appears (e.g. an API key loaded from a .env file)."""
        self.register_secrets([value])

    def register_secrets(self, values: Iterable[str | None]) -> None:
        new = {str(v) for v in values if v is not None and len(str(v).strip()) >= _MIN_SECRET_LEN
               and str(v).strip().lower() not in ("true", "false", "none", "null")}
        if not new:
            return
        with self._lock:
            self._secrets |= new
            ordered = sorted(self._secrets, key=len, reverse=True)
            self._secret_re = re.compile("|".join(re.escape(s) for s in ordered))

    def is_sensitive_key(self, key: Any) -> bool:
        k = _norm_key(key)
        return k in self._keys or bool(_SENSITIVE_KEY_RE.search(k))

    # ---- masking ------------------------------------------------------------------------------
    def redact_text(self, text: str) -> str:
        if not text:
            return text
        if self._secret_re is not None:
            text = self._secret_re.sub(REDACTED, text)
        for pattern, repl in self._credential_patterns:
            text = pattern.sub(repl, text)
        if self.enabled:
            for pattern, repl in self._patterns:
                text = pattern.sub(repl, text)
            if self.redact_emails:
                text = _EMAIL_RE.sub(REDACTED_EMAIL, text)
        return text

    def redact(self, value: Any, _depth: int = 0) -> Any:
        """Return a redacted deep copy of a JSON-like value (dict / list / str / scalars)."""
        if _depth > self.max_depth:
            return "[TRUNCATED_DEPTH]"
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, Mapping):
            out = {}
            for k, v in value.items():
                if self.is_sensitive_key(k) and v not in (None, "", [], {}):
                    out[k] = REDACTED
                else:
                    out[k] = self.redact(v, _depth + 1)
            return out
        if isinstance(value, (list, tuple, set, frozenset)):
            return [self.redact(v, _depth + 1) for v in value]
        return value

    @classmethod
    def from_settings(cls, settings: Any, secrets: Iterable[str] = ()) -> "Redactor":
        extra_secrets = list(secrets)
        key = getattr(settings, "langsmith_api_key", None)
        if key is not None:
            extra_secrets.append(key.get_secret_value())
        return cls(enabled=settings.redaction_enabled, redact_emails=settings.redact_emails,
                   redact_financial=settings.redact_financial_identifiers, extra_fields=settings.redact_fields,
                   extra_patterns=settings.redact_patterns, secrets=extra_secrets)
