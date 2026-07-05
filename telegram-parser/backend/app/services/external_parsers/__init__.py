"""In-process adapters for the three integrated external parsers.

Each adapter drives a Telegram client built from a *combine* account
(proxy enforced, session reused via :mod:`app.services.session_bridge`)
and applies the matching algorithm ported verbatim from the upstream
repository it wraps. Matches are written into the
``external_parser_runs`` row (CSV + ``result_count``) so the rest of the
combine (UI, contact import) sees them through the existing pattern.

Why in-process instead of running the repos as subprocesses: the
upstream scripts authenticate with their own file-based sessions and
hard-coded credentials. Reusing the combine's Pyrogram/Telethon
infrastructure (the explicit requirement) is cleanest in-process, and
it keeps the integration unit-testable without a live account.
"""
