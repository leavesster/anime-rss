#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CONTAINERS=()
TEMP_DIR=$(mktemp -d)
IMAGES=(
  "lscr.io/linuxserver/qbittorrent:version-4.6.7-r0@sha256:55f15d44396315551f87294a176efae733b16e283f38980308e46073950257c6|v4.6.7"
  "lscr.io/linuxserver/qbittorrent:version-5.0.4-r0@sha256:46f4e80af074fa2ffc0214fe0b7d59384748cfb34685892a53b7a3c87407a333|v5.0.4"
)

cleanup() {
  if ((${#CONTAINERS[@]})); then
    docker stop "${CONTAINERS[@]}" >/dev/null 2>&1 || true
  fi
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

for specification in "${IMAGES[@]}"; do
  image=${specification%%|*}
  expected=${specification##*|}
  config_dir="$TEMP_DIR/$expected"
  mkdir -p "$config_dir/qBittorrent"
  printf '%s\n' \
    '[Preferences]' \
    'WebUI\AuthSubnetWhitelist=0.0.0.0/0' \
    'WebUI\AuthSubnetWhitelistEnabled=true' \
    'WebUI\HostHeaderValidation=false' \
    > "$config_dir/qBittorrent/qBittorrent.conf"
  docker pull "$image" >/dev/null
  container=$(docker run --detach --rm \
    --env PUID=1000 \
    --env PGID=1000 \
    --env WEBUI_PORT=8080 \
    --publish 127.0.0.1::8080/tcp \
    --volume "$config_dir:/config" \
    "$image")
  CONTAINERS+=("$container")

  address=$(docker port "$container" 8080/tcp | sed -n '/127\.0\.0\.1/p' | head -1)
  "$ROOT/.venv/bin/python" "$ROOT/backend/scripts/check_qbittorrent_contract.py" \
    --url "http://$address" \
    --username contract \
    --password contract \
    --expect-version "$expected"
  docker stop "$container" >/dev/null
done

CONTAINERS=()
