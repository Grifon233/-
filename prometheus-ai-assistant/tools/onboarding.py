"""Save / validate / mask API keys in HERMES_HOME/.env.

Companion to :mod:`tools.key_detector`. The detector decides *whether*
a message contains a key; this module decides *how* to persist it
safely: chown 600, idempotent overwrite, atomic temp-file write, and
optional provider-specific validation through a cheap test request.

This module is intentionally NOT a security boundary — it has no
opinion about *who* is allowed to write the file. Authorization
(``tools.file_safety``, owner checks, etc.) is enforced by the caller.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


# Per-provider validation. Each entry returns (ok: bool, detail: str).
# ``detail`` is a short human-readable message ("key works, balance $X.XX"
# or "key rejected: 401 Unauthorized"). The caller decides what to show.
#
# Adding a new provider: drop a new entry below and the key detector's
# _PROVIDER_TO_ENV_VAR map will route the right env-var to the right
# validator automatically.
_VALIDATORS = {}


def register_validator(env_var: str, fn) -> None:
    """Register or replace a validator for ``env_var`` (used in tests)."""
    _VALIDATORS[env_var] = fn


# --- Default validators -----------------------------------------------------


def _validate_polza(api_key: str) -> "ValidationResult":
    """Cheap test request against polza.ai's OpenAI-compatible endpoint.

    Sends a 1-token completion on the cheapest likely-available model.
    If the model isn't available, the request still returns 401 (bad key)
    vs 402/403 (key OK, billing issue) vs 200 (success), which is enough
    signal to confirm the credential is alive.
    """
    try:
        import httpx  # local import — httpx is a base dep of Hermes
    except Exception as exc:  # pragma: no cover - import guard
        return ValidationResult(ok=None, detail=f"validator unavailable: {exc}")

    url = "https://polza.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "openai/gpt-4o-mini",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=15.0)
    except httpx.HTTPError as exc:
        return ValidationResult(ok=False, detail=f"network error: {exc}")

    if resp.status_code == 200:
        return ValidationResult(ok=True, detail="key accepted")
    if resp.status_code in (401, 403):
        # Try to extract a useful detail from the response body.
        try:
            body = resp.json()
            err = body.get("error", {}).get("message") if isinstance(body, dict) else None
        except Exception:
            err = None
        return ValidationResult(ok=False, detail=err or f"rejected (HTTP {resp.status_code})")
    # 402/429/etc. — key is probably fine, just blocked for another reason.
    return ValidationResult(
        ok=None,
        detail=f"key probably valid (HTTP {resp.status_code}); not used for verdict",
    )


def _validate_openai_compatible(api_key: str, base_url: str, model: str) -> "ValidationResult":
    """Generic OpenAI-compatible endpoint validator.

    Used as a fallback for any provider whose env-var doesn't have a
    dedicated validator: a 1-token test completion is enough to confirm
    the credential works.
    """
    try:
        import httpx
    except Exception as exc:
        return ValidationResult(ok=None, detail=f"validator unavailable: {exc}")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    try:
        resp = httpx.post(f"{base_url.rstrip('/')}/chat/completions",
                          headers=headers, json=payload, timeout=15.0)
    except httpx.HTTPError as exc:
        return ValidationResult(ok=False, detail=f"network error: {exc}")

    if resp.status_code == 200:
        return ValidationResult(ok=True, detail="key accepted")
    if resp.status_code in (401, 403):
        try:
            body = resp.json()
            err = body.get("error", {}).get("message") if isinstance(body, dict) else None
        except Exception:
            err = None
        return ValidationResult(ok=False, detail=err or f"rejected (HTTP {resp.status_code})")
    return ValidationResult(
        ok=None,
        detail=f"key probably valid (HTTP {resp.status_code}); not used for verdict",
    )


# Register built-in validators. Order matters: more-specific first.
register_validator("POLZA_AI_API_KEY", _validate_polza)
register_validator("POLZA_API_KEY", _validate_polza)
register_validator("OPENAI_API_KEY",
                   lambda k: _validate_openai_compatible(k, "https://api.openai.com/v1", "gpt-4o-mini"))
register_validator("OPENROUTER_API_KEY",
                   lambda k: _validate_openai_compatible(k, "https://openrouter.ai/api/v1", "openai/gpt-4o-mini"))


# --- File I/O ---------------------------------------------------------------


def env_path(hermes_home: Optional[Path] = None) -> Path:
    """Return the absolute path to ``HERMES_HOME/.env``."""
    if hermes_home is None:
        from hermes_constants import get_hermes_home
        hermes_home = get_hermes_home()
    return Path(hermes_home) / ".env"


def mask_value(value: str, *, head: int = 4, tail: int = 4) -> str:
    """Return a masked version of ``value`` for display in chat.

    ``sk-abc123def456`` → ``sk-a*********f456`` (or similar). Pure function;
    never logs the original. Works for short tokens too (returns the
    whole value if it's shorter than ``head + tail``).
    """
    if not value:
        return ""
    if len(value) <= head + tail + 3:
        # Too short to mask meaningfully — show first 2 chars + bullets.
        return (value[:2] + "***") if len(value) > 2 else "***"
    return f"{value[:head]}{'*' * (len(value) - head - tail)}{value[-tail:]}"


def read_env(hermes_home: Optional[Path] = None) -> dict[str, str]:
    """Parse ``HERMES_HOME/.env`` into a dict.

    Order-preserving for the same key (last write wins), values are
    stripped of surrounding quotes, and lines starting with ``#`` are
    ignored. Returns an empty dict if the file is missing.
    """
    path = env_path(hermes_home)
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip surrounding single or double quotes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def write_env(env: dict[str, str], hermes_home: Optional[Path] = None) -> Path:
    """Atomically write ``env`` to ``HERMES_HOME/.env`` with mode 600.

    Overwrites the whole file (not in-place edit) so comments and order
    are preserved by the caller passing the full env dict. Returns the
    path that was written. On POSIX, applies ``chmod 600``; on Windows,
    the ACL inherits the parent directory (ACL mode not enforced here
    because the only writer is the running agent process).
    """
    path = env_path(hermes_home)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    for key, value in env.items():
        # Quote values containing whitespace or special chars; leave
        # simple alnum values unquoted for readability.
        if re.search(r"[\s\"'$\\`,;]", value):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key}="{escaped}"')
        else:
            lines.append(f"{key}={value}")
    body = "\n".join(lines) + "\n" if lines else ""

    # Atomic write: temp file in the same directory, then rename.
    fd, tmp_name = tempfile.mkstemp(prefix=".env.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    # Permissions: only the owner can read/write. Best-effort on Windows.
    try:
        os.chmod(path, 0o600)
    except (OSError, NotImplementedError):
        pass

    logger.info("Wrote %d keys to %s", len(env), path)
    return path


def save_to_env(
    name: str,
    value: str,
    hermes_home: Optional[Path] = None,
    *,
    overwrite: bool = True,
) -> "SaveResult":
    """Persist a single ``name=value`` pair in ``HERMES_HOME/.env``.

    Atomic write, mode 600. If ``overwrite`` is False and the key already
    exists, returns ok=False with ``reason="exists"`` — the caller is
    expected to ask the user for confirmation before retrying.
    """
    if not name or not value:
        return SaveResult(ok=False, reason="invalid", path=env_path(hermes_home))
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        return SaveResult(ok=False, reason="invalid_name", path=env_path(hermes_home))

    env = read_env(hermes_home)
    if name in env and not overwrite:
        return SaveResult(ok=False, reason="exists", path=env_path(hermes_home),
                          existing=env[name])

    env[name] = value
    path = write_env(env, hermes_home)
    return SaveResult(ok=True, path=path)


def delete_from_env(name: str, hermes_home: Optional[Path] = None) -> "SaveResult":
    """Remove ``name`` from ``HERMES_HOME/.env``. No-op if absent."""
    env = read_env(hermes_home)
    if name in env:
        del env[name]
        write_env(env, hermes_home)
        return SaveResult(ok=True, path=env_path(hermes_home))
    return SaveResult(ok=False, reason="not_found", path=env_path(hermes_home))


def list_masked_env(hermes_home: Optional[Path] = None) -> List["MaskedKey"]:
    """Return all keys in ``.env`` with their values masked for display.

    Used by /users, /status, /whereismykey, and onboarding summaries.
    """
    return [
        MaskedKey(name=k, display=mask_value(v))
        for k, v in sorted(read_env(hermes_home).items())
    ]


def validate_key(name: str, value: str) -> "ValidationResult":
    """Run the registered validator for ``name`` against ``value``.

    Returns ``ValidationResult(ok=None, detail='no validator for <name>')``
    if no provider-specific validator is registered — the caller is
    expected to treat ``ok=None`` as "skip the verdict, just save".
    """
    fn = _VALIDATORS.get(name)
    if fn is None:
        return ValidationResult(ok=None, detail=f"no validator for {name}")
    try:
        return fn(value)
    except Exception as exc:  # validator blew up — don't crash the chat flow
        logger.warning("validator for %s raised: %s", name, exc, exc_info=True)
        return ValidationResult(ok=None, detail=f"validator error: {exc}")


# --- Result dataclasses -----------------------------------------------------


@dataclass(frozen=True)
class SaveResult:
    ok: bool
    path: Path
    reason: Optional[str] = None      # "invalid" | "invalid_name" | "exists" | "not_found"
    existing: Optional[str] = None    # the value already on disk, if reason=="exists"


@dataclass(frozen=True)
class ValidationResult:
    ok: Optional[bool]   # True = works, False = rejected, None = inconclusive
    detail: str          # human-readable explanation


@dataclass(frozen=True)
class MaskedKey:
    name: str
    display: str         # already-masked value, safe to show in chat


__all__ = [
    "env_path", "mask_value", "read_env", "write_env",
    "save_to_env", "delete_from_env", "list_masked_env", "validate_key",
    "SaveResult", "ValidationResult", "MaskedKey",
    "register_validator",
]
