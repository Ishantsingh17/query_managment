"""FastAPI entrypoint for the Audit Evidence Platform."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from observability import get_observability

from app.api import auth, dashboard, evidence, mcp_http, requests
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.telemetry import setup_observability
from app.db.seed_config import seed_config
from app.db.session import create_schema, session_scope, validate_schema
from app.mock_sources import store
from app.mock_sources.api import router as mock_router

log = logging.getLogger(__name__)


def bootstrap() -> None:
    settings = get_settings()
    setup_observability()
    for d in (settings.evidence_staging_dir, settings.packages_dir, settings.storage_dir / "db"):
        d.mkdir(parents=True, exist_ok=True)
    create_schema()
    with session_scope() as s:
        seed_config(s)
    validate_schema()
    store.seed_sources()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    bootstrap()
    log.info("Audit Evidence Platform started", extra={"event": "startup"})
    yield
    get_observability().shutdown()  # flush the local log and pending LangSmith batches


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    install_error_handlers(app)
    for r in (auth.router, requests.router, dashboard.router, evidence.router, mcp_http.router, mock_router):
        app.include_router(r)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
