"""Local evidence staging layout (Backend Schema §7)."""
import json
import re
from pathlib import Path
from typing import Any

from app.core.config import get_settings


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120]


def request_dir(request_id: str) -> Path:
    return get_settings().evidence_staging_dir / _safe(request_id)


def ensure_dirs(request_id: str) -> Path:
    base = request_dir(request_id)
    for sub in ("original", "normalized", "manual_uploads"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def write_original(request_id: str, filename: str, content: bytes) -> Path:
    path = ensure_dirs(request_id) / "original" / _safe(filename)
    path.write_bytes(content)
    return path


def write_normalized(request_id: str, evidence_id: str, payload: dict[str, Any]) -> Path:
    path = ensure_dirs(request_id) / "normalized" / f"{_safe(evidence_id)}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def write_manual_upload(request_id: str, filename: str, content: bytes) -> Path:
    path = ensure_dirs(request_id) / "manual_uploads" / _safe(filename)
    if path.exists():
        path = path.with_name(f"{path.stem}_{len(list(path.parent.iterdir()))}{path.suffix}")
    path.write_bytes(content)
    return path


def relative(path: Path | str) -> str:
    """Store paths relative to the storage root in the DB."""
    p = Path(path)
    try:
        return p.resolve().relative_to(get_settings().storage_dir.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def absolute(rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else get_settings().storage_dir / p
