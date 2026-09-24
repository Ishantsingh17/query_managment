"""Observability wiring for this application.

The reusable, business-agnostic module lives in `backend/observability`; this file only supplies app context
(environment, service name, .env location, app secrets that must be masked). Agents call the generic API
(`get_observability().agent(...)`, `.llm_call(...)`, ...) and never talk to LangSmith or the log file directly.
"""
from observability import ObservabilityManager, ObservabilitySettings, configure_observability

from app.core.config import BACKEND_ROOT, get_settings

SERVICE_NAME = "audit-evidence-platform"


def setup_observability() -> ObservabilityManager:
    s = get_settings()
    obs_settings = ObservabilitySettings.load(BACKEND_ROOT / ".env")
    defaults = {}
    if "environment" not in obs_settings.model_fields_set:
        defaults["environment"] = s.environment
    if "service_name" not in obs_settings.model_fields_set:
        defaults["service_name"] = SERVICE_NAME
    if defaults:
        obs_settings = obs_settings.model_copy(update=defaults)
    # Secrets read from backend/.env by the app's own settings are not in os.environ; register them explicitly.
    secrets = [s.groq_api_key, s.gmail_app_password, s.gmail_oauth_client_secret, s.gmail_oauth_refresh_token,
               s.secret_key]
    return configure_observability(obs_settings, secrets=[v for v in secrets if v], base_dir=BACKEND_ROOT)
