"""Application configuration.

All tunables live here and are driven by environment variables so nothing
demo-specific is hard-coded. Secrets are never logged.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/
BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM -------------------------------------------------------------
    # GROQ_MODEL is deliberately configurable; the TRD forbids assuming a
    # permanently available model id.
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_timeout_seconds: float = 30.0

    # --- Workflow --------------------------------------------------------
    # Bounds the retry loop so it cannot spin forever.
    max_retries: int = 2
    # Paces workflow stages so the sequential DB search is visible during a
    # live demo. Set to 0 for tests and instant runs.
    demo_step_delay_ms: int = 700

    # --- Storage ---------------------------------------------------------
    data_root: Path = BACKEND_ROOT
    app_state_db_name: str = "app_state.sqlite"

    # First demo request becomes AUD-00124, matching the UI mockups.
    request_id_seed: int = 123
    request_id_prefix: str = "AUD-"

    @property
    def databases_dir(self) -> Path:
        return self.data_root / "databases"

    @property
    def mock_documents_dir(self) -> Path:
        return self.data_root / "mock_documents"

    @property
    def evidence_staging_dir(self) -> Path:
        return self.data_root / "evidence_staging"

    @property
    def final_packages_dir(self) -> Path:
        return self.data_root / "final_audit_packages"

    @property
    def app_state_db_path(self) -> Path:
        return self.data_root / self.app_state_db_name

    @property
    def catalog_dir(self) -> Path:
        return BACKEND_ROOT / "app" / "catalog"

    @property
    def groq_enabled(self) -> bool:
        return bool(self.groq_api_key.strip())

    def ensure_directories(self) -> None:
        """Create every runtime directory. Safe to call repeatedly."""
        for path in (
            self.databases_dir,
            self.mock_documents_dir,
            self.evidence_staging_dir,
            self.final_packages_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        for sub in (
            "invoices",
            "purchase_orders",
            "grns",
            "ses",
            "supporting",
            "reports",
            "confirmations",
        ):
            (self.mock_documents_dir / sub).mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
