import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="aep-test-"))
os.environ["AEP_STORAGE_DIR"] = str(_TMP)
os.environ["AEP_MOCK_LATENCY_MS"] = "0"
os.environ["AEP_NOTIFICATION_PROVIDER"] = "console"
os.environ["AEP_LLM_PROVIDER"] = "rules"
# Observability: local JSONL in a temp dir (outside AEP_STORAGE_DIR, which is wiped per test); never send to LangSmith.
_OBS_TMP = Path(tempfile.mkdtemp(prefix="aep-obs-"))
os.environ["OBSERVABILITY_LOG_FILE"] = str(_OBS_TMP / "llm_observability.jsonl")
os.environ["OBSERVABILITY_ENVIRONMENT"] = "test"
os.environ["LANGSMITH_ENABLED"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"
# Never route test notifications to real inboxes configured in backend/.env
for _k in ("AEP_NOTIFICATION_RECIPIENT_OVERRIDE", "AEP_NOTIFY_VALIDATOR_EMAIL", "AEP_NOTIFY_SME_EMAIL", "AEP_NOTIFY_AUDITOR_EMAIL"):
    os.environ[_k] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db import session as db_session  # noqa: E402
from app.main import app, bootstrap  # noqa: E402
from app.mcp.gateway import McpGateway, set_gateway  # noqa: E402
from app.mock_sources import store  # noqa: E402
from app.notifications import service as notif  # noqa: E402
from app.orchestrator import intake  # noqa: E402

PASSWORD = "Password@123"


class RecordingProvider:
    channel = "GMAIL"
    status_on_success = "SENT"

    def __init__(self):
        self.sent = []
        self.fail = False

    def send(self, recipient, subject, text, html):
        if self.fail:
            raise RuntimeError("SMTP unavailable")
        self.sent.append({"to": recipient, "subject": subject, "text": text, "html": html})


@pytest.fixture()
def env():
    """Fresh DBs + storage per test."""
    get_settings.cache_clear()
    intake.clear_cache()
    settings = get_settings()
    if settings.storage_dir.exists():
        shutil.rmtree(settings.storage_dir, ignore_errors=True)
    db_session.init_engine(settings.db_url)
    store.reset_source_engine(None)
    bootstrap()
    store.seed_sources(force=True)
    provider = RecordingProvider()
    notif.set_provider(provider)
    client = TestClient(app)
    set_gateway(McpGateway(client=TestClient(app)))  # MCP connectors call the mock APIs in-process
    yield {"client": client, "provider": provider}
    set_gateway(None)
    notif.set_provider(None)
    db_session.get_engine().dispose()
    store.get_source_engine().dispose()


def login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture()
def auditor(env):
    return login(env["client"], "sarah.mitchell@company.com")


@pytest.fixture()
def validator(env):
    return login(env["client"], "david.okafor@company.com")


@pytest.fixture()
def sme(env):
    return login(env["client"], "priya.raman@company.com")
