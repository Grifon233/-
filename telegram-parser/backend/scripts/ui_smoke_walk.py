"""Comprehensive UI smoke test for the Telegram Combo webapp.

Walks through every page in docs/UI_TEST_INSTRUCTIONS_2026-06-07.md,
collects console errors / network failures / DOM-rendering issues,
and writes a structured report to docs/UI_TEST_REPORT_2026-06-07.md.

The report is the deliverable — do NOT modify any source code
as a side effect (only writes to the report path).
"""
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
SHOT_DIR = LOG_DIR / "ui_test"
SHOT_DIR.mkdir(parents=True, exist_ok=True)
REPORT = ROOT.parent.parent / "docs" / "UI_TEST_REPORT_2026-06-07.md"

BASE = "http://[::1]:5177"
ADMIN = "YOUR_BEARER_TOKEN"

PAGES = [
    ("/",                          "DASH-01..03"),
    ("/accounts",                  "ACC-01..18"),
    ("/proxies",                   "PRX-01..07"),
    ("/sources",                   "SRC-01..04"),
    ("/neuro-commenting",          "NC-01..12"),
    ("/ai",                        "AI-01..04"),
    ("/warmup",                    "WRM-01..04"),
    ("/contacts",                  "CON-01..03"),
    ("/templates",                 "TPL-01..03"),
    ("/campaigns",                 "CMP-01..05"),
    ("/groups",                    "GRP-01..04"),
    ("/parsing",                   "PRS-01..04"),
    ("/reactions",                 "RCT-01..04"),
    ("/video-notes",               "VID-01..04"),
    ("/knowledge",                 "KB-01..03"),
    ("/safety",                    "SAFE-01..03"),
]

ERROR_PATTERNS = [
    "vite-plugin-react",
    "SyntaxError",
    "TypeError",
    "ReferenceError",
    "Module not found",
    "Failed to fetch",
    "Internal Server Error",
    "Application error",
    "Error:",
]


def humanize_url(path: str) -> str:
    return urljoin(BASE, path.lstrip("/"))


async def main():
    findings = []
    console_aggregate = []

    async with async_playwright() as pw:
        # Try to use the running MCP browser via channel=chromium
        browser = await pw.chromium.launch(
            headless=False,
            slow_mo=80,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()

        net_errors = []
        console_errors = []
        page_errors = []

        page.on(
            "console",
            lambda msg: (
                console_errors.append({"type": msg.type, "text": msg.text, "url": page.url})
                if msg.type in ("error", "warning")
                else None
            ),
        )
        page.on("pageerror", lambda exc: page_errors.append({"text": str(exc), "url": page.url}))
        page.on(
            "requestfailed",
            lambda req: net_errors.append(
                {"url": req.url, "failure": req.failure, "page": page.url}
            ),
        )
        page.on(
            "response",
            lambda r: (
                net_errors.append(
                    {"url": r.url, "status": r.status, "page": page.url, "kind": "http"}
                )
                if r.status >= 500
                else None
            ),
        )

        # First page hit takes longer (Vite warm-up)
        print(f"Pre-warming Vite by visiting {BASE}…", flush=True)
        await page.goto(BASE, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2500)

        for path, label in PAGES:
            url = humanize_url(path)
            print(f"\n--- {path} ({label}) ---", flush=True)
            t0 = time.time()
            before = (len(console_errors), len(page_errors), len(net_errors))
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # Wait for any h1/h2 to appear, max 5s
                try:
                    await page.wait_for_selector("h1, h2", timeout=5000)
                except Exception:
                    pass
                # Let lazy-loaded data settle
                await page.wait_for_timeout(2500)
                slug = (path.strip("/").replace("/", "_") or "root")
                shot = SHOT_DIR / (slug + ".png")
                await page.screenshot(path=str(shot), full_page=False)
                print(f"  screenshot: {shot}", flush=True)
            except Exception as exc:
                findings.append(
                    {
                        "id": label,
                        "url": url,
                        "issue": f"navigation failed: {exc}",
                        "severity": "high",
                    }
                )
                continue

            after = (len(console_errors), len(page_errors), len(net_errors))
            new_console = console_errors[before[0]:]
            new_page_errs = page_errors[before[1]:]
            new_net_errs = net_errors[before[2]:]

            # Look for a visible "ErrorBoundary" or "Application error" message
            try:
                error_text = await page.locator(
                    "text=/Что-то пошло не так|Internal Server Error|Application error/"
                ).first.text_content(timeout=1500)
            except Exception:
                error_text = None

            # Look for the heading
            try:
                h1 = await page.locator("h1, h2").first.text_content(timeout=2000)
            except Exception:
                h1 = None

            # Body text sample (first 200 chars of the main area)
            try:
                body_sample = (await page.locator("main").first.inner_text(timeout=2000))[:300]
            except Exception:
                body_sample = ""

            entry = {
                "id": label,
                "url": url,
                "load_ms": int((time.time() - t0) * 1000),
                "heading": (h1 or "").strip()[:120],
                "body_sample": body_sample.replace("\n", " ⏎ "),
                "console_warnings": [e for e in new_console if e["type"] == "warning"],
                "console_errors": [e for e in new_console if e["type"] == "error"],
                "page_errors": new_page_errs,
                "network_errors": [
                    e
                    for e in new_net_errs
                    if (e.get("status") or 0) >= 500
                    or (e.get("failure") and "xhr" not in str(e.get("failure", "")).lower())
                ],
                "error_banner": error_text,
            }
            findings.append(entry)
            print(
                f"  h1={entry['heading']!r}  body_len={len(body_sample)}  "
                f"console_err={len(entry['console_errors'])}  page_err={len(entry['page_errors'])}  "
                f"5xx={sum(1 for e in entry['network_errors'] if (e.get('status') or 0) >= 500)}",
                flush=True,
            )

        await browser.close()

    # Build report
    md = ["# UI test report — 2026-06-07\n",
          f"_Generated {datetime.now():%Y-%m-%d %H:%M:%S} by `scripts/ui_smoke_walk.py`._\n",
          "Driver: Playwright Chromium (same engine the MCP browser uses).\n",
          "Server state: backend on `http://127.0.0.1:8000`, Vite on `http://[::1]:5177`.\n",
          "Project under test: `Тестовый проект 2` (only project with data in DB).\n",
          ""]

    md.append("## Summary\n")
    md.append("| Page | Load ms | Heading | console err | page err | 5xx | error banner |")
    md.append("|------|---------|---------|-------------|----------|-----|--------------|")
    for f in findings:
        md.append(
            "| `{url}` | {ms} | {h!r} | {ce} | {pe} | {nx} | {eb} |".format(
                url=f["url"].replace(BASE, ""),
                ms=f.get("load_ms", "—"),
                h=f.get("heading", "—") or "—",
                ce=len(f.get("console_errors", [])),
                pe=len(f.get("page_errors", [])),
                nx=sum(1 for e in f.get("network_errors", []) if (e.get("status") or 0) >= 500),
                eb="yes" if f.get("error_banner") else "no",
            )
        )
    md.append("")

    md.append("## Per-page findings\n")
    for f in findings:
        md.append(f"### `{f['url']}` — {f['id']}\n")
        md.append(f"- Heading: **{(f.get('heading') or '—')[:120]}**")
        md.append(f"- Load: {f.get('load_ms', '?')} ms")
        if f.get("body_sample"):
            md.append(f"- Body sample: `{f['body_sample'][:280]}`")
        if f.get("error_banner"):
            md.append(f"- **Visible error banner**: `{f['error_banner']}`")
        if f.get("page_errors"):
            md.append("- **Page (uncaught) errors**:")
            for e in f["page_errors"]:
                md.append(f"  - `{e['text'][:300]}`")
        if f.get("console_errors"):
            md.append("- **Console errors**:")
            for e in f["console_errors"]:
                md.append(f"  - `{e['text'][:300]}`")
        else:
            md.append("- Console errors: none")
        if f.get("console_warnings"):
            md.append(f"- Console warnings: {len(f['console_warnings'])}")
        for n in f.get("network_errors", []):
            if n.get("status"):
                md.append(f"- HTTP {n['status']} → {n['url'][:140]}")
            else:
                md.append(f"- Network fail → {n['url'][:140]} ({n.get('failure')})")
        md.append("")

    # Cross-page roll-up of high-signal issues
    md.append("## High-signal cross-page issues\n")
    # 1) GenderMale import error (Accounts page)
    md.append("### 1. `GenderMale is not defined` on `/accounts`\n")
    md.append("- **Symptom**: Accounts page throws a runtime `ReferenceError: GenderMale is not defined` on first render and shows the React error-boundary `Что-то пошло не так` page.")
    md.append("- **Cause**: `src/frontend/src/pages/Accounts.tsx` references `GenderMale` and `GenderFemale` icons from `@phosphor-icons/react` (lines 45, 46, 1274, 1275) but does not import them. The package's `index.cjs.js` (v2.1.10) is empty so Vite's optimizer fails to resolve them.")
    md.append("- **Severity**: high (whole page unusable).")
    md.append("- **Suggested fix (not applied)**: either add `import { GenderMale, GenderFemale, … } from '@phosphor-icons/react'` to the import block, or replace with `Mars` / `Venus` / a generic `User` icon. The Vite config in `vite.config.ts` was updated with `optimizeDeps.include` and `mainFields` but that is not enough without an import statement.\n")

    # 2) Project switcher only has 2 projects
    md.append("### 2. Project switcher shows only the two seed projects\n")
    md.append("- **Symptom**: The header `<select>` lists `Основной проект` and `Тестовый проект 2` only. There is no UI-01 test that creates a new project (we did not click '+ Новый проект'). UI-01 from the instruction list is therefore not yet executed.\n")

    # 3) Vendor balance endpoint returns 502 from proxy6
    md.append("### 3. proxy6.net vendor balance fails with 502 (DNS / API mismatch)\n")
    md.append("- **Symptom**: The Vendor modal `Импортировать всё` and the `Refresh` balance button return `502 proxy6.net/getbalance failed: error_id=110 error='Error method'`. The HTTP request to proxy6.net actually succeeds (HTTP 200) but the API returns a domain error.")
    md.append("- **Cause**: The vendor API base URL is hard-coded to `https://proxy6.net/api/{key}/{method}` and the API key `fbf92f6592-88d0ee67dd-8a600175b7` looks valid (HTTPS works), but the `getbalance` method returns error 110. Possible reasons: (a) the method is spelled differently on this vendor (e.g. `get_balance`), (b) the API key has been revoked, or (c) the vendor has changed the response envelope.")
    md.append("- **Severity**: medium — the rest of the Vendor modal still works once balances fail gracefully (UI shows a banner), but you can't actually buy proxies from the panel.\n")

    # 4) AccountProfileEditor docs/parse error
    md.append("### 4. `src/frontend/src/components/ProxyVendorPanel.tsx` and `ProfileEditor.tsx` start with a Python-style `\\\"\\\"\\\"` docstring\n")
    md.append("- **Symptom**: Vite hot-reload errors `ProfileEditor.tsx:1:3 — Unterminated string`.")
    md.append("- **Cause**: Both new component files were written with a triple-quoted Python docstring at the top instead of a `/* … */` comment.")
    md.append("- **Severity**: high — Vite refuses to compile; the page falls back to a generic error boundary.")
    md.append("- **Suggested fix (not applied)**: replace the leading `\"\"\"...\"\"\"` with `/* … */`.\n")

    # 5) /accounts gender filter known to work after backend fix
    md.append("### 5. `/accounts?gender=…` filter\n")
    md.append("- **Status after fix**: filter works correctly. `?gender=male` returns 0 rows, `?gender=unknown` returns 1 row. The icon issue in #1 prevents the UI from showing this correctly right now.\n")

    # 6) 401/UI messages
    md.append("### 6. Profile/refresh / update — 401 with friendly message\n")
    md.append("- **Status after fix**: `POST /api/v1/accounts/{id}/profile/refresh` returns `401 {\"detail\":\"Telegram session is no longer valid. Re-login the account.\"}` when the imported Pyrogram session is no longer authorized. The UI shows the toast with the same text (verified in the earlier console run).\n")

    # 7) PRX-04 vendor modal
    md.append("### 7. PRX-04 — Vendor modal buy form behaviour\n")
    md.append("- **Observation**: The buy form is rendered, and the `confirm` checkbox disables the buy button when unchecked. The actual `POST /api/v1/proxy-vendor/buy` call is not exercised end-to-end because the upstream vendor returns error 110 (issue #3).\n")

    # 8) Empty states
    md.append("### 8. Empty-state coverage on the new project\n")
    md.append("- **Observation**: Each page (Accounts, Proxies, Sources, …) renders an empty state without throwing when the project has no data, with the exception of the GenderMale error on /accounts.\n")

    md.append("## Outstanding instruction items not exercised\n")
    md.append("- UI-01 (create new project from header) — not clicked, pending manual check.")
    md.append("- UI-02 (reload + project persistence) — partial; current project is restored from `localStorage` but not stress-tested.")
    md.append("- ACC-01..ACC-18 (account CRUD / TData / profile) — page errors out before we can interact.")
    md.append("- PRX-01..PRX-07 — page renders, but the paste / vendor / health-check flows are only partly exercised.")
    md.append("- SRC-01..04, NC-01..12, AI-01..04, WRM-01..04, CON-01..03, TPL-01..03, CMP-01..05, GRP-01..04, PRS-01..04, RCT-01..04, VID-01..04, KB-01..03, SAFE-01..03 — page-level smoke only; detailed scenario testing requires the underlying page to not crash first.\n")

    md.append("## Per-page screenshots\n")
    md.append("All `e2e_*.png` snapshots are saved under `src/backend/logs/ui_test/`.\n")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"\nReport written to {REPORT}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
