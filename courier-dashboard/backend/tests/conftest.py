"""Do not open a production database or connect to integrations under pytest."""
import os

# Set before app.config or app.main is imported by a test module.
os.environ.update({
    "STORE_BACKEND": "memory",
    "SIGHTINGS_DB_PATH": "",
    "INGEST_API_KEY": "",
    "INGEST_ALLOW_UNAUTHENTICATED": "0",
    "SIGHTING_TTL": "7200",
    "SIGHTING_MAX_FUTURE_SKEW": "300",
    "ANTHROPIC_API_KEY": "",
    "LLM_API_KEYS_FILE": "",
    "LLM_ALLOW_PRIVATE_TEXT": "0",
    "LLM_CLOUDFLARE_ACCOUNT_ID": "",
    "NOMINATIM_URL": "",
    "VALHALLA_URL": "",
    "FEEDBACK_BOT_TOKEN": "",
    "FEEDBACK_CHAT_ID": "",
    "FEEDBACK_RATE_LIMIT": "5",
    "FEEDBACK_GLOBAL_RATE_LIMIT": "30",
})
