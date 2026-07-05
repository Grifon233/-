"""Detect API keys and bot tokens in chat messages.

Used by the Telegram gateway to offer one-tap "save to .env" when a user
pastes a credential. NOT a security scanner — the goal is friendly UX,
so patterns are tuned for high precision (few false positives), not for
catching every leak. Defense-in-depth (skills_guard, file_safety, etc.)
remains the real safety net.

Detection strategies (first match wins, in priority order):

1. ``KEY=VALUE`` pairs at line boundaries (e.g. ``POLZA_AI_API_KEY=polza-abc``).
2. Bare provider-prefixed tokens (``sk-...``, ``sk-ant-...``, ``AIza...``,
   ``polza-...``, ``ghp_...``, ``AKIA...``).
3. Telegram bot tokens (numeric:base64 pattern).

Every hit is returned with a confidence score and a human-readable provider
label so the gateway can show "looks like an OpenAI key" instead of just
"found a key".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


# --- KEY=VALUE pairs (most reliable; one match per line) -------------------
#
# Captures: name (uppercase, underscores, digits; starts with letter or _),
# value (everything to end of line, no spaces, no quotes required).
#
# Length floor on VALUE: 8 chars — short enough to catch shorter
# polza.ai / generic API keys (12+ chars) while staying above
# short-hash / port / version false positives. The 8-char floor is
# the most common tunable in similar detectors; raise it if you start
# catching URLs or version strings, lower it if legit short keys
# are missed.
#
# Anchoring: KEY must be preceded by start-of-line or non-word char
# (so we don't catch `key=value` inside an arbitrary identifier or
# path). VALUE must end at a non-word char or end-of-string so we
# don't accidentally capture a suffix that happens to be
# alphanumeric (e.g. ``OPENAI_API_KEY=sk-abc&foo=bar`` stops at ``&``).
_KV_PAIR_RE = re.compile(
    r"""(?:^|(?<=[^\w/]))([A-Z_][A-Z0-9_]{1,})\s*=\s*([^\s'"#,\]]{8,})(?=[^\w/-]|$)"""
)

# Map of well-known env-var names → human-readable provider label.
# Matched case-sensitively against the captured KEY name above.
_KNOWN_ENV_VARS = {
    "POLZA_AI_API_KEY":      "polza.ai API key",
    "POLZA_API_KEY":         "polza.ai API key",
    "OPENAI_API_KEY":        "OpenAI API key",
    "OPENAI_BASE_URL":       "OpenAI base URL",
    "OPENAI_ORG_ID":         "OpenAI org id",
    "OPENROUTER_API_KEY":    "OpenRouter API key",
    "ANTHROPIC_API_KEY":     "Anthropic API key",
    "ANTHROPIC_TOKEN":       "Anthropic token",
    "CLAUDE_CODE_OAUTH_TOKEN": "Claude Code OAuth token",
    "GOOGLE_API_KEY":        "Google API key",
    "GEMINI_API_KEY":        "Gemini API key",
    "DEEPSEEK_API_KEY":      "DeepSeek API key",
    "MISTRAL_API_KEY":       "Mistral API key",
    "GROQ_API_KEY":          "Groq API key",
    "TOGETHER_API_KEY":      "Together API key",
    "PERPLEXITY_API_KEY":    "Perplexity API key",
    "COHERE_API_KEY":        "Cohere API key",
    "FIREWORKS_API_KEY":     "Fireworks API key",
    "XAI_API_KEY":           "xAI API key",
    "FIRECRAWL_API_KEY":     "Firecrawl API key",
    "TELEGRAM_BOT_TOKEN":    "Telegram bot token",
    "DISCORD_BOT_TOKEN":     "Discord bot token",
    "GH_TOKEN":              "GitHub personal token",
    "GITHUB_TOKEN":          "GitHub token",
    "GITHUB_PAT":            "GitHub PAT",
    "AWS_ACCESS_KEY_ID":     "AWS access key id",
    "AWS_SECRET_ACCESS_KEY": "AWS secret access key",
    "HUGGINGFACE_API_KEY":   "HuggingFace API key",
    "HF_TOKEN":              "HuggingFace token",
    "REPLICATE_API_TOKEN":   "Replicate API token",
    "ELEVENLABS_API_KEY":    "ElevenLabs API key",
    "OPENAI_ASSISTANTS_KEY": "OpenAI Assistants key",
    "AZURE_OPENAI_API_KEY":  "Azure OpenAI key",
    "MODAL_TOKEN_ID":        "Modal token id",
    "MODAL_TOKEN_SECRET":    "Modal token secret",
    "DAYTONA_API_KEY":       "Daytona API key",
}


# --- Bare provider-prefixed tokens ------------------------------------------
#
# Order matters: longer / more specific prefixes must be tried first so
# ``sk-ant-...`` doesn't get matched as ``sk-...``.
_PREFIX_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),  "Anthropic API key"),
    (re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"), "OpenAI project key"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"),        "OpenAI API key"),
    (re.compile(r"AIza[A-Za-z0-9_-]{35}"),      "Google API key"),
    (re.compile(r"polza-[A-Za-z0-9_-]{16,}"),   "polza.ai API key"),
    (re.compile(r"AKIA[0-9A-Z]{16}"),           "AWS access key id"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"),        "GitHub personal token"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{60,}"), "GitHub fine-grained PAT"),
    (re.compile(r"gho_[A-Za-z0-9]{36}"),        "GitHub OAuth token"),
    (re.compile(r"ghu_[A-Za-z0-9]{36}"),        "GitHub user token"),
    (re.compile(r"ghs_[A-Za-z0-9]{36}"),        "GitHub server token"),
    (re.compile(r"ghr_[A-Za-z0-9]{36}"),        "GitHub refresh token"),
    (re.compile(r"xai-[A-Za-z0-9]{20,}"),       "xAI API key"),
    (re.compile(r"hf_[A-Za-z0-9]{20,}"),        "HuggingFace token"),
    (re.compile(r"r8_[A-Za-z0-9]{20,}"),        "Replicate token"),
]


# --- Telegram bot tokens ----------------------------------------------------
#
# Format: ``<bot_id>:<token>`` where bot_id is 8-10 digits and token is
# 35 chars of [A-Za-z0-9_-]. Anchored with word boundaries so we don't
# grab random ``123456:abcdef...`` substrings inside other text.
_TELEGRAM_BOT_TOKEN_RE = re.compile(
    r"\b(\d{8,10}:[A-Za-z0-9_-]{35,40})\b"
)


@dataclass(frozen=True)
class DetectedKey:
    """One API key / bot token found in user-supplied text.

    Attributes:
        name: Suggested env-var name. For KEY=VALUE pairs, the literal KEY.
              For bare tokens, a sensible default env-var name for the
              detected provider.
        value: The credential value (NEVER truncated; never logged).
        provider_label: Human-readable provider name (e.g. "polza.ai API key").
        confidence: ``"high"`` (KEY=VALUE with known env-var name OR
                    provider-specific prefix), ``"medium"`` (bare prefix
                    with heuristic env-var mapping), ``"low"`` (other).
    """
    name: str
    value: str
    provider_label: str
    confidence: str


# Heuristic env-var name for each provider when no KEY=VALUE is supplied.
# Keep in sync with the labels used by key_audit / providers tooling.
_PROVIDER_TO_ENV_VAR = {
    "polza.ai API key":            "POLZA_AI_API_KEY",
    "OpenAI API key":              "OPENAI_API_KEY",
    "OpenAI project key":          "OPENAI_API_KEY",
    "Anthropic API key":           "ANTHROPIC_API_KEY",
    "Google API key":              "GOOGLE_API_KEY",
    "AWS access key id":           "AWS_ACCESS_KEY_ID",
    "GitHub personal token":       "GH_TOKEN",
    "GitHub fine-grained PAT":     "GH_TOKEN",
    "GitHub OAuth token":          "GH_TOKEN",
    "GitHub user token":           "GH_TOKEN",
    "GitHub server token":         "GH_TOKEN",
    "GitHub refresh token":        "GH_TOKEN",
    "xAI API key":                 "XAI_API_KEY",
    "HuggingFace token":           "HF_TOKEN",
    "Replicate token":             "REPLICATE_API_TOKEN",
    "Telegram bot token":          "TELEGRAM_BOT_TOKEN",
}


def _bare_token_default_name(label: str) -> str:
    return _PROVIDER_TO_ENV_VAR.get(label, "API_KEY")


def detect_api_keys(text: str) -> List[DetectedKey]:
    """Scan ``text`` for API keys, bot tokens, and KEY=VALUE pairs.

    Returns a list of :class:`DetectedKey` (possibly empty). Order:
    KEY=VALUE pairs first, then bare provider-prefixed tokens, then
    Telegram bot tokens. Duplicates (same ``name``+``value``) are removed.
    """
    if not text or not text.strip():
        return []

    found: dict[str, DetectedKey] = {}  # name → DetectedKey (de-dup by name)
    seen_values: set[str] = set()

    def _add(name: str, value: str, label: str, confidence: str) -> None:
        if value in seen_values:
            return
        # If a previous match already claimed this name, prefer the
        # higher-confidence one. Otherwise overwrite.
        existing = found.get(name)
        if existing is not None and existing.confidence == "high":
            return
        seen_values.add(value)
        found[name] = DetectedKey(
            name=name, value=value, provider_label=label, confidence=confidence
        )

    # 1) KEY=VALUE pairs at line boundaries.
    for m in _KV_PAIR_RE.finditer(text):
        name = m.group(1)
        value = m.group(2)
        if name in _KNOWN_ENV_VARS:
            _add(name, value, _KNOWN_ENV_VARS[name], "high")
        elif name.endswith(("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")) and len(value) >= 24:
            _add(name, value, name.replace("_", " ").lower(), "medium")
        # else: looks like a normal config (URL, short hash, etc.) — skip.

    # 2) Bare provider-prefixed tokens.
    for pattern, label in _PREFIX_PATTERNS:
        for m in pattern.finditer(text):
            value = m.group(0)
            env_var = _bare_token_default_name(label)
            _add(env_var, value, label, "high")

    # 3) Telegram bot tokens (standalone format).
    for m in _TELEGRAM_BOT_TOKEN_RE.finditer(text):
        value = m.group(1)
        _add("TELEGRAM_BOT_TOKEN", value, "Telegram bot token", "high")

    return list(found.values())


def first_api_key(text: str) -> Optional[DetectedKey]:
    """Convenience: return the first detected key, or None.

    Useful for the gateway's "one key at a time" confirm flow.
    """
    hits = detect_api_keys(text)
    return hits[0] if hits else None


__all__ = [
    "DetectedKey",
    "detect_api_keys",
    "first_api_key",
]
