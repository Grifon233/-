#!/usr/bin/env bash
set -euo pipefail

base=/opt/master-booking
current_target=$(readlink -f "$base/current")

case "$current_target" in
  "$base"/releases/*) ;;
  *) printf 'Unsafe current target: %s\n' "$current_target" >&2; exit 1 ;;
esac

grep -q 'WorkingDirectory=/opt/master-booking/current' /etc/systemd/system/mb-backend.service
grep -q 'EnvironmentFile=/opt/master-booking/shared/.env' /etc/systemd/system/mb-backend.service

paths=(
  "$base/AGENTS.md" "$base/architect" "$base/backend" "$base/bot" "$base/CLAUDE.md"
  "$base/data" "$base/deploy.ps1" "$base/docs" "$base/.env" "$base/.env.example"
  "$base/GEMINI.md" "$base/.github" "$base/.gitignore" "$base/init_db.py" "$base/logs"
  "$base/master_booking.db" "$base/master-bot" "$base/master_bot" "$base/PROJECT_MAP.md"
  "$base/pytest.ini" "$base/README.md" "$base/requirements.txt" "$base/run_architect.py"
  "$base/run_bot.py" "$base/.secrets" "$base/setup-server.sh" "$base/start_bot.sh"
  "$base/sync-server.ps1" "$base/tests" "$base/uploads" "$base/venv" "$base/web"
)

for target in "${paths[@]}"; do
  case "$target" in
    "$base"/*) rm -rf -- "$target" ;;
    *) printf 'Unsafe cleanup target: %s\n' "$target" >&2; exit 1 ;;
  esac
done

printf 'ROOT_AFTER\n'
find "$base" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort
printf 'HEALTH\n'
curl -fsS http://127.0.0.1:8000/api/health
