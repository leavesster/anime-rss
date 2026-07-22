#!/usr/bin/env bash
set -euo pipefail

IMAGE=${IMAGE:-}
if [[ -z "$IMAGE" ]]; then
  printf 'Usage: IMAGE=<container-image> make image-smoke\n' >&2
  exit 2
fi

RUN_ID=${RUN_ID:-$RANDOM-$$}
CONTAINER="anime-rss-smoke-$RUN_ID"
VOLUME="anime-rss-smoke-$RUN_ID-data"

cleanup() {
  status=$?
  if ((status != 0)); then
    docker logs "$CONTAINER" >&2 2>/dev/null || true
  fi
  docker rm --force "$CONTAINER" >/dev/null 2>&1 || true
  docker volume rm --force "$VOLUME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker volume create "$VOLUME" >/dev/null
docker run --detach --name "$CONTAINER" \
  --publish 127.0.0.1::8080/tcp \
  --volume "$VOLUME:/data" \
  "$IMAGE" >/dev/null

address=$(docker port "$CONTAINER" 8080/tcp | sed -n '/127\.0\.0\.1/p' | head -1)
for _ in $(seq 1 90); do
  if curl --fail --silent "http://$address/api/v1/health/ready" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

curl --fail --silent "http://$address/api/v1/health/ready" | grep -q '"status":"ready"'
curl --fail --silent "http://$address/" | grep -q '<div id="root"></div>'
docker exec "$CONTAINER" anime-rss doctor --data-dir /data | grep -q '^PASS    schema: at head:'
test "$(docker exec "$CONTAINER" id -u)" != "0"
for _ in $(seq 1 30); do
  health=$(docker inspect --format '{{.State.Health.Status}}' "$CONTAINER")
  if [[ "$health" == "healthy" ]]; then
    break
  fi
  if [[ "$health" == "unhealthy" ]]; then
    exit 1
  fi
  sleep 1
done
test "$(docker inspect --format '{{.State.Health.Status}}' "$CONTAINER")" = "healthy"

printf 'Image smoke passed for %s.\n' "$IMAGE"
