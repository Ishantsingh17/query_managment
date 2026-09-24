"""Fixtures for the observability module's own tests (independent of any host application)."""
import os
from pathlib import Path

import pytest

from observability import ObservabilityManager, ObservabilitySettings, reset_observability
from observability.query import iter_events


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Tests must not depend on (or leak into) the developer's environment."""
    for k in list(os.environ):
        if k.startswith(("OBSERVABILITY_", "LANGSMITH_", "LANGCHAIN_")):
            monkeypatch.delenv(k, raising=False)
    yield
    reset_observability()


@pytest.fixture()
def log_path(tmp_path: Path) -> Path:
    return tmp_path / "logs" / "llm_observability.jsonl"


@pytest.fixture()
def make_obs(log_path):
    """Factory: an ObservabilityManager writing to a temp JSONL file, LangSmith off unless overridden."""
    created: list[ObservabilityManager] = []

    def make(**overrides) -> ObservabilityManager:
        opts = {"log_file": log_path, "langsmith_enabled": False, **overrides}
        sinks = opts.pop("sinks", None)
        redactor = opts.pop("redactor", None)
        secrets = opts.pop("secrets", ())
        m = ObservabilityManager(ObservabilitySettings(**opts), sinks=sinks, redactor=redactor, secrets=secrets)
        created.append(m)
        return m
    yield make
    for m in created:
        m.shutdown()


@pytest.fixture()
def read(log_path):
    def _read(obs: ObservabilityManager | None = None) -> list[dict]:
        if obs is not None:
            obs.flush()
        return list(iter_events(log_path))
    return _read


@pytest.fixture()
def langsmith_capture(monkeypatch):
    """Intercept LangSmith HTTP writes at the SDK boundary (after its hide_inputs/hide_outputs hooks ran)."""
    import langsmith
    posts: list[dict] = []
    patches: list[dict] = []
    monkeypatch.setattr(langsmith.Client, "_create_run", lambda self, rc: posts.append(rc))
    monkeypatch.setattr(langsmith.Client, "_update_run", lambda self, ru: patches.append(ru))

    def runs() -> dict[str, dict]:
        by: dict[str, dict] = {}
        for p in posts:
            by[str(p["id"])] = dict(p)
        for p in patches:
            by.setdefault(str(p["id"]), {}).update({k: v for k, v in p.items() if v is not None})
        return by
    return {"posts": posts, "patches": patches, "runs": runs}
