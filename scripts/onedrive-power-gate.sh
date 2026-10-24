#!/bin/bash
# Run the OneDrive ingester only on mains power. Invoked every 5 minutes by the
# LaunchAgent in scripts/uk.aiapplied.second-brain.onedrive-power-gate.plist.
set -euo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE=ingester-onedrive
CONTAINER=sb-ingester-onedrive

docker info >/dev/null 2>&1 || exit 0 # Docker Desktop not running: nothing to do

running="$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || echo false)"
if pmset -g batt | head -1 | grep -q "AC Power"; then
  if [ "$running" != "true" ]; then
    echo "$(date '+%F %T') on AC power: starting $SERVICE"
    docker compose -f "$REPO/infra/docker-compose.yml" --profile onedrive up -d "$SERVICE"
  fi
elif [ "$running" = "true" ]; then
  echo "$(date '+%F %T') on battery: stopping $SERVICE"
  docker stop "$CONTAINER" >/dev/null
fi
