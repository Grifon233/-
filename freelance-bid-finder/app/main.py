from __future__ import annotations

import sys

from flask import Flask, jsonify, render_template, request

from app import db
from app.ai_replies import AIReplyError, generate_reply
from app.config import load_config
from app.scanner import ScannerService


config = load_config()
db.init_db()
scanner = ScannerService(config)


def create_app(start_scheduler: bool = True) -> Flask:
    app = Flask(__name__)

    if start_scheduler:
        scanner.start(run_immediately=True)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/leads")
    def api_leads():
        source = request.args.get("source") or None
        unread_only = request.args.get("unread") == "1"
        query = request.args.get("q") or None
        return jsonify(
            {
                "ok": True,
                "items": db.list_leads(
                    source=source,
                    unread_only=unread_only,
                    query=query,
                ),
            }
        )

    @app.get("/api/stats")
    def api_stats():
        payload = db.get_stats()
        payload["scanner"] = scanner.status()
        return jsonify({"ok": True, **payload})

    @app.get("/api/leads/hidden")
    def api_hidden_leads():
        return jsonify({"ok": True, "items": db.list_hidden_leads()})

    @app.get("/api/leads/actions")
    def api_action_leads():
        return jsonify({"ok": True, "items": db.list_action_leads()})

    @app.post("/api/scan")
    def api_scan():
        started = scanner.run_async()
        return jsonify({"ok": True, "started": started, "scanner": scanner.status()})

    @app.post("/api/leads/<int:lead_id>/read")
    def api_read(lead_id: int):
        is_read = bool((request.get_json(silent=True) or {}).get("is_read", True))
        db.mark_read(lead_id, is_read=is_read)
        return jsonify({"ok": True})

    @app.post("/api/leads/read-all")
    def api_read_all():
        db.mark_all_read()
        return jsonify({"ok": True})

    @app.post("/api/leads/<int:lead_id>/hide")
    def api_hide(lead_id: int):
        db.hide_lead(lead_id)
        return jsonify({"ok": True})

    @app.post("/api/leads/<int:lead_id>/restore")
    def api_restore(lead_id: int):
        db.restore_lead(lead_id)
        return jsonify({"ok": True})

    @app.post("/api/leads/<int:lead_id>/ai-reply")
    def api_ai_reply(lead_id: int):
        lead = db.get_lead(lead_id)
        if not lead:
            return jsonify({"ok": False, "error": "Заявка не найдена"}), 404
        try:
            result = generate_reply(lead)
        except AIReplyError as error:
            return jsonify({"ok": False, "error": str(error)}), 502
        return jsonify({"ok": True, **result})

    return app


app = create_app(start_scheduler="--scan-once" not in sys.argv)


if __name__ == "__main__":
    if "--scan-once" in sys.argv:
        print(scanner.run_once())
        raise SystemExit(0)

    app.run(
        host=config["web"]["host"],
        port=int(config["web"]["port"]),
        debug=False,
        use_reloader=False,
    )
