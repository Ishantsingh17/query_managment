"""Application configuration (environment-driven)."""
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_ROOT / ".env", env_prefix="AEP_", extra="ignore")

    app_name: str = "Audit Evidence Platform"
    environment: str = "development"
    log_level: str = "INFO"

    # Storage
    storage_dir: Path = BACKEND_ROOT / "storage"
    database_url: str = ""  # defaults to storage/db/audit_evidence.sqlite
    source_database_url: str = ""  # defaults to storage/db/source_mocks.sqlite

    # Security
    secret_key: str = "dev-only-change-me"
    token_ttl_minutes: int = 8 * 60

    # Web app link used in notifications
    app_base_url: str = "http://localhost:5173"
    # Base URL the MCP connectors use to reach the (mock) source APIs
    source_api_base_url: str = "http://127.0.0.1:8000"
    source_api_timeout_seconds: float = 10.0
    mock_latency_ms: int = 250

    # Retrieval / retry policy (configurable, per TRD §7)
    retrieval_max_attempts: int = 2

    # LLM. "rules" = deterministic built-in agents; "groq" = ChatGroq; "langchain" = init_chat_model(llm_model)
    llm_provider: str = "rules"
    llm_model: str = "openai/gpt-oss-120b"
    llm_timeout_seconds: float = 30.0
    # When the LLM is enabled, let the Retrieval Agent drive MCP tool calls (deterministic fallback always kept)
    llm_agentic_retrieval: bool = True
    groq_api_key: str = Field("", validation_alias=AliasChoices("GROQ_API_KEY", "AEP_GROQ_API_KEY"))

    # Notifications: "console" logs only; "gmail" = Gmail SMTP + App Password (ports 465/587);
    # "gmail_api" = Gmail API over HTTPS/443 with OAuth (works where SMTP is blocked)
    notification_provider: str = "console"
    gmail_sender: str = "singhishant01feb@gmail.com"
    gmail_app_password: str = ""
    gmail_smtp_port: int = 465  # 465 = SSL, 587 = STARTTLS
    gmail_oauth_client_id: str = ""
    gmail_oauth_client_secret: str = ""
    gmail_oauth_refresh_token: str = ""
    # Dev safety valve: route every notification to this inbox instead of the user's address
    notification_recipient_override: str = ""
    # Dev: per-role recipients (take precedence over the global override) — demo accounts use fabricated addresses
    notify_validator_email: str = ""
    notify_sme_email: str = ""
    notify_auditor_email: str = ""

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.storage_dir / 'db' / 'audit_evidence.sqlite').as_posix()}"

    @property
    def source_db_url(self) -> str:
        return self.source_database_url or f"sqlite:///{(self.storage_dir / 'db' / 'source_mocks.sqlite').as_posix()}"

    @property
    def evidence_staging_dir(self) -> Path:
        return self.storage_dir / "evidence_staging"

    @property
    def packages_dir(self) -> Path:
        return self.storage_dir / "packages"


@lru_cache
def get_settings() -> Settings:
    return Settings()
