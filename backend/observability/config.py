"""Environment-driven configuration (Pydantic Settings).

Every setting is read from the process environment (and optionally a `.env` file passed by the host
application via `ObservabilitySettings(_env_file=...)`). Nothing is hard-coded; secrets are `SecretStr`
so they never appear in reprs, logs or events.
"""
import json
import logging
from pathlib import Path
from typing import Annotated, Any

from pydantic import AliasChoices, Field, PrivateAttr, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

log = logging.getLogger("observability")


def _env(*names: str) -> AliasChoices:
    return AliasChoices(*names)


class ObservabilitySettings(BaseSettings):
    """All knobs of the observability module. Safe-by-default: no payload capture, redaction on,
    remote tracing off unless LangSmith is explicitly enabled *and* an API key is present."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True, case_sensitive=False)

    # ---- global -------------------------------------------------------------------------------
    enabled: bool = Field(True, validation_alias=_env("OBSERVABILITY_ENABLED"))
    environment: str = Field("development", validation_alias=_env("OBSERVABILITY_ENVIRONMENT"))
    service_name: str | None = Field(None, validation_alias=_env("OBSERVABILITY_SERVICE_NAME"))
    fail_open: bool = Field(True, validation_alias=_env("OBSERVABILITY_FAIL_OPEN"))

    # ---- LangSmith sink -----------------------------------------------------------------------
    langsmith_enabled: bool = Field(True, validation_alias=_env("LANGSMITH_ENABLED"))
    langsmith_tracing: bool = Field(False, validation_alias=_env("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"))
    langsmith_api_key: SecretStr | None = Field(None, validation_alias=_env("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"))
    langsmith_project: str | None = Field(None, validation_alias=_env("LANGSMITH_PROJECT", "LANGCHAIN_PROJECT"))
    langsmith_endpoint: str | None = Field(None, validation_alias=_env("LANGSMITH_ENDPOINT", "LANGCHAIN_ENDPOINT"))

    # ---- local JSONL sink ---------------------------------------------------------------------
    log_file_enabled: bool = Field(True, validation_alias=_env("OBSERVABILITY_LOG_FILE_ENABLED"))
    log_file: Path = Field(Path("logs/llm_observability.jsonl"), validation_alias=_env("OBSERVABILITY_LOG_FILE"))
    log_rotation_enabled: bool = Field(False, validation_alias=_env("OBSERVABILITY_LOG_ROTATION_ENABLED"))
    log_max_bytes: int = Field(50 * 1024 * 1024, ge=1024, validation_alias=_env("OBSERVABILITY_LOG_MAX_BYTES"))
    log_backup_count: int = Field(5, ge=1, le=100, validation_alias=_env("OBSERVABILITY_LOG_BACKUP_COUNT"))
    queue_size: int = Field(10_000, ge=10, validation_alias=_env("OBSERVABILITY_QUEUE_SIZE"))

    # ---- payload capture (off by default) -----------------------------------------------------
    capture_inputs: bool = Field(False, validation_alias=_env("OBSERVABILITY_CAPTURE_INPUTS"))
    capture_outputs: bool = Field(False, validation_alias=_env("OBSERVABILITY_CAPTURE_OUTPUTS"))
    capture_messages: bool = Field(False, validation_alias=_env("OBSERVABILITY_CAPTURE_MESSAGES"))
    max_payload_chars: int = Field(4000, ge=64, validation_alias=_env("OBSERVABILITY_MAX_PAYLOAD_CHARS"))
    llm_step_events: bool = Field(False, validation_alias=_env("OBSERVABILITY_LLM_STEP_EVENTS"))

    # ---- redaction ----------------------------------------------------------------------------
    redaction_enabled: bool = Field(True, validation_alias=_env("OBSERVABILITY_REDACTION_ENABLED"))
    redact_emails: bool = Field(True, validation_alias=_env("OBSERVABILITY_REDACT_EMAILS"))
    redact_financial_identifiers: bool = Field(False, validation_alias=_env("OBSERVABILITY_REDACT_FINANCIAL_IDENTIFIERS"))
    redact_fields: Annotated[list[str], NoDecode] = Field(default_factory=list, validation_alias=_env("OBSERVABILITY_REDACT_FIELDS"))
    redact_patterns: Annotated[list[str], NoDecode] = Field(default_factory=list, validation_alias=_env("OBSERVABILITY_REDACT_PATTERNS"))

    # ---- usage / cost -------------------------------------------------------------------------
    token_estimation_enabled: bool = Field(False, validation_alias=_env("OBSERVABILITY_TOKEN_ESTIMATION_ENABLED"))
    cost_tracking_enabled: bool = Field(False, validation_alias=_env("OBSERVABILITY_COST_TRACKING_ENABLED",
                                                                     "OBSERVABILITY_PRICING_ENABLED"))
    input_cost_per_1k_tokens: float | None = Field(None, ge=0, validation_alias=_env("OBSERVABILITY_INPUT_COST_PER_1K_TOKENS"))
    output_cost_per_1k_tokens: float | None = Field(None, ge=0, validation_alias=_env("OBSERVABILITY_OUTPUT_COST_PER_1K_TOKENS"))
    # Optional per-model overrides: {"model": {"input_cost_per_1k_tokens": 0.1, "output_cost_per_1k_tokens": 0.2}}
    model_pricing: dict[str, dict[str, float]] = Field(default_factory=dict, validation_alias=_env("OBSERVABILITY_MODEL_PRICING"))
    cost_currency: str = Field("USD", validation_alias=_env("OBSERVABILITY_COST_CURRENCY"))

    # Names of settings that failed validation (populated only by `load` when it fell back to defaults).
    _config_errors: list[str] = PrivateAttr(default_factory=list)

    @field_validator("redact_fields", "redact_patterns", mode="before")
    @classmethod
    def _split_list(cls, v: Any) -> Any:
        """Accept a JSON list or a comma-separated string (patterns: JSON list only, since regexes contain commas)."""
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            if s.startswith("["):
                return json.loads(s)
            return [p.strip() for p in s.split(",") if p.strip()]
        return v

    @field_validator("langsmith_api_key", "langsmith_project", "langsmith_endpoint", "service_name", mode="before")
    @classmethod
    def _blank_is_none(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else v

    # ---- derived ------------------------------------------------------------------------------
    @property
    def langsmith_active(self) -> bool:
        """LangSmith receives data only when observability, the adapter and tracing are all on and a key exists."""
        return bool(self.enabled and self.langsmith_enabled and self.langsmith_tracing
                    and self.langsmith_api_key and self.langsmith_api_key.get_secret_value())

    def resolved_log_file(self, base_dir: Path | None = None) -> Path:
        p = Path(self.log_file).expanduser()
        return p if p.is_absolute() else (base_dir or Path.cwd()) / p

    @classmethod
    def load(cls, env_file: str | Path | None = None, **overrides: Any) -> "ObservabilitySettings":
        """Load from the environment (+ optional .env). Invalid configuration never raises: a warning is
        logged and safe defaults are used, so a telemetry misconfiguration cannot stop the host app."""
        try:
            return cls(_env_file=env_file, **overrides) if env_file else cls(**overrides)
        except (ValidationError, ValueError) as exc:
            fields = sorted({".".join(map(str, e["loc"])) for e in getattr(exc, "errors", lambda: [])()})
            log.warning("invalid observability configuration (%s); using safe defaults", ", ".join(fields) or exc.__class__.__name__)
            defaults = cls.model_construct()
            defaults._config_errors = fields or [exc.__class__.__name__]
            return defaults

    @property
    def config_errors(self) -> list[str]:
        return list(self._config_errors)
