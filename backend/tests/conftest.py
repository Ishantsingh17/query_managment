"""Test fixtures.

Every test runs against a throwaway data root with freshly seeded mock
databases, so tests never touch the developer's working data and cannot
affect one another.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "scripts"))


@pytest.fixture(scope="session", autouse=True)
def _isolated_environment(tmp_path_factory):
    """Point the app at a temporary data root with no pacing delay."""
    data_root = tmp_path_factory.mktemp("audit_data")

    os.environ["DATA_ROOT"] = str(data_root)
    os.environ["DEMO_STEP_DELAY_MS"] = "0"
    os.environ["MAX_RETRIES"] = "2"
    # Force the deterministic parser so tests never depend on the network.
    os.environ["GROQ_API_KEY"] = ""

    from app.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    assert settings.data_root == data_root
    assert settings.demo_step_delay_ms == 0
    settings.ensure_directories()

    import seed_databases

    seed_databases.seed()

    from app.services import db

    db.initialize()

    yield settings


@pytest.fixture
def client(_isolated_environment):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def run_request(client):
    """Create and run a request, returning its final detail payload."""

    def _run(query: str) -> dict:
        created = client.post("/api/audit-requests", json={"query": query})
        assert created.status_code == 201, created.text
        request_id = created.json()["request_id"]
        # TestClient executes background tasks before returning the response.
        client.post(f"/api/audit-requests/{request_id}/run")
        response = client.get(f"/api/audit-requests/{request_id}")
        assert response.status_code == 200, response.text
        return response.json()

    return _run


@pytest.fixture
def evidence_sources():
    """Map evidence code -> source database id for a detail payload."""

    def _map(detail: dict) -> dict[str, str]:
        return {
            item["document_type"]: item["source_database_id"]
            for item in detail["retrieved_evidence"]
        }

    return _map
