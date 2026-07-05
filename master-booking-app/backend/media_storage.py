import os
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_UPLOAD_PREFIX = "/api/uploads/"


def get_upload_dir() -> Path:
    configured = Path(os.environ.get("UPLOAD_DIR", "uploads")).expanduser()
    upload_dir = configured if configured.is_absolute() else PROJECT_ROOT / configured
    upload_dir = upload_dir.resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def public_upload_url(filename: str) -> str:
    return f"{PUBLIC_UPLOAD_PREFIX}{filename}"


def normalize_media_reference(value: str | None) -> str | None:
    """Keep uploaded media on the current public host, including legacy URLs."""
    if not value:
        return None

    value = value.strip()
    if not value:
        return None

    parsed = urlsplit(value)
    path = parsed.path or ""
    if path.startswith("/uploads/"):
        path = f"/api{path}"

    if path.startswith(PUBLIC_UPLOAD_PREFIX):
        suffix = f"?{parsed.query}" if parsed.query else ""
        return f"{path}{suffix}"

    return value
