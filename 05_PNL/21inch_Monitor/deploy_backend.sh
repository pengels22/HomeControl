#!/usr/bin/env bash
# Deploy the 21-inch Home Assistant backend with rollback on failure.
set -euo pipefail
SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET=/opt/homecontrol/21inch-monitor
UNIT=homecontrol-21inch.service
DROPIN=/etc/systemd/system/homecontrol-21inch.service.d
CONFIG=/home/pi/.config/homecontrol-21inch/ha.env
BACKUP="$(mktemp -d /tmp/homecontrol21-deploy.XXXXXXXX)"
[[ $(id -u) == 0 ]] || { echo "Run: sudo bash deploy_backend.sh"; exit 1; }
[[ -s "$CONFIG" ]] || { echo "Missing HA token config: $CONFIG"; exit 1; }
grep -q '^HA_TOKEN=' "$CONFIG" || { echo "HA_TOKEN variable missing in $CONFIG"; exit 1; }
[[ -f "$TARGET/approved_trace.svg" ]] || { echo "Existing approved trace not found: $TARGET"; exit 1; }
python3 -c 'import flask, requests' || { echo "Install python3-flask python3-requests"; exit 1; }
mkdir -p "$DROPIN"
cp -a "$TARGET" "$BACKUP/dashboard"
if [[ -e "$DROPIN/override.conf" ]]; then cp -a "$DROPIN/override.conf" "$BACKUP/override.conf"; fi
rollback(){
  echo "Deployment failed; restoring previous dashboard and service."
  cp -a "$BACKUP/dashboard/." "$TARGET/"
  if [[ -f "$BACKUP/override.conf" ]]; then
     cp -a "$BACKUP/override.conf" "$DROPIN/override.conf"
  else
     rm -f "$DROPIN/override.conf"
  fi
  systemctl daemon-reload
  systemctl restart "$UNIT" || true
}
trap rollback ERR
for file in backend.py live_ha.js static_apartment.js static_apartment_config.js index.html; do
  install -m 0644 "$SOURCE/$file" "$TARGET/$file"
done
python3 -m py_compile "$TARGET/backend.py"
cat > "$DROPIN/override.conf" <<'EOF'
[Service]
EnvironmentFile=/home/pi/.config/homecontrol-21inch/ha.env
Environment=MONITOR_PORT=8765
ExecStart=
ExecStart=/usr/bin/python3 /opt/homecontrol/21inch-monitor/backend.py
EOF
systemctl daemon-reload
systemctl restart "$UNIT"
sleep 2
curl -fsS --max-time 12 http://127.0.0.1:8765/api/health | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d); assert d.get("home_assistant")=="connected"'
curl -fsS --max-time 12 http://127.0.0.1:8765/api/entities | python3 -c 'import sys,json; states=json.load(sys.stdin); print("Live entities:",len(states)); assert any(x.get("entity_id","").startswith("light.") for x in states)'
trap - ERR
echo "SUCCESS: HomeControl kiosk now serves authenticated HA backend on localhost:8765."
echo "Backup retained at: $BACKUP"
