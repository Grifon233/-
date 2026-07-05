#!/usr/bin/env bash
set -euo pipefail

base=/opt/master-booking
archive=${1:-/tmp/master-booking-release.tar.gz}
release=$(date +%Y%m%d-%H%M%S)
release_dir=$base/releases/$release

test -f "$archive"
mkdir -p "$base/releases" "$base/shared/uploads" "$base/shared/logs" "$base/backups" "$release_dir"

if [ ! -f "$base/shared/.env" ]; then
  cp -a "$base/.env" "$base/shared/.env"
fi
if [ ! -f "$base/shared/master_booking.db" ]; then
  cp -a "$base/master_booking.db" "$base/shared/master_booking.db"
fi
if [ -d "$base/uploads" ] && [ ! -L "$base/uploads" ]; then
  cp -a "$base/uploads/." "$base/shared/uploads/"
fi
if [ -d "$base/logs" ] && [ ! -L "$base/logs" ]; then
  cp -a "$base/logs/." "$base/shared/logs/"
fi

# Keep shared secrets stable across releases. In particular,
# AUTH_SIGNING_SECRET must survive deploys so previously issued links remain valid.
cp -a "$base/shared/master_booking.db" "$base/backups/master_booking-$release.db"

tar -xzf "$archive" -C "$release_dir"
ln -s "$base/shared/.env" "$release_dir/.env"
ln -s "$base/shared/master_booking.db" "$release_dir/master_booking.db"
case "$release_dir" in
  "$base"/releases/*) rm -rf "$release_dir/uploads" "$release_dir/logs" ;;
  *) printf 'Unsafe release path: %s\n' "$release_dir" >&2; exit 1 ;;
esac
ln -s "$base/shared/uploads" "$release_dir/uploads"
ln -s "$base/shared/logs" "$release_dir/logs"

python3 -m venv "$release_dir/venv"
"$release_dir/venv/bin/pip" install --disable-pip-version-check -q -r "$release_dir/requirements.txt"
(
  cd "$release_dir/web"
  npm ci --no-audit --no-fund --loglevel=error
  npm run build
  rm -rf "$release_dir/web/node_modules"
)
(
  cd "$release_dir"
  "$release_dir/venv/bin/python" -c "import backend.main; print('backend import ok')"
)

chown -R botuser:botuser "$release_dir" "$base/shared" "$base/backups"
ln -sfn "$release_dir" "$base/current.next"
mv -Tf "$base/current.next" "$base/current"

sed -i \
  -e 's#WorkingDirectory=/opt/master-booking$#WorkingDirectory=/opt/master-booking/current#' \
  -e 's#EnvironmentFile=/opt/master-booking/.env#EnvironmentFile=/opt/master-booking/shared/.env#' \
  -e 's#/opt/master-booking/venv/bin/python#/opt/master-booking/current/venv/bin/python#' \
  /etc/systemd/system/mb-backend.service /etc/systemd/system/mb-architect.service
sed -i \
  's#root /opt/master-booking/web/dist;#root /opt/master-booking/current/web/dist;#' \
  /etc/nginx/sites-enabled/master-booking

systemctl daemon-reload
nginx -t
systemctl restart mb-backend mb-architect nginx
rm -f "$archive"

printf 'DEPLOYED_RELEASE=%s\n' "$release"
