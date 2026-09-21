"""FastAPI application entry point.

Local POC only: no authentication, no deployment concerns.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.catalog.loader import enabled_databases, load_use_cases
from app.config import get_settings
from app.services import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Automated Audit Evidence Retrieval",
    description="Turn an auditor's natural-language request into a validated evidence package.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    # Next falls back to 3001, 3002, ... when 3000 is taken, so allow the
    # local dev range rather than a single port. Local POC only.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):30\d{2}",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
def on_startup() -> None:
    settings = get_settings()
    settings.ensure_directories()
    db.initialize()

    use_cases = load_use_cases()
    databases = enabled_databases()
    # Never log the API key itself, only whether one is present.
    logger.info(
        "Ready: %d use cases, %d searchable databases (%s), Groq=%s, model=%s, step delay=%dms",
        len(use_cases),
        len(databases),
        ", ".join(db_spec.database_id for db_spec in databases),
        "configured" if settings.groq_enabled else "not configured (rule-based fallback)",
        settings.groq_model,
        settings.demo_step_delay_ms,
    )

    missing = [
        spec.database_id
        for spec in databases
        if not spec.resolved_path(settings.data_root).exists()
    ]
    if missing:
        logger.warning(
            "Database files missing for %s - run scripts/seed_databases.py", ", ".join(missing)
        )


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    databases = enabled_databases()
    return {
        "status": "ok",
        "use_cases": len(load_use_cases()),
        "databases": [
            {
                "database_id": spec.database_id,
                "search_order": spec.search_order,
                "available": spec.resolved_path(settings.data_root).exists(),
            }
            for spec in databases
        ],
        "groq_configured": settings.groq_enabled,
        "groq_model": settings.groq_model,
        "demo_step_delay_ms": settings.demo_step_delay_ms,
        "max_retries": settings.max_retries,
    }
