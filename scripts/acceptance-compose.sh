#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

CURRENT_IMAGE=${CURRENT_IMAGE:-anime-rss-service:acceptance-current}
BASELINE_IMAGE=${BASELINE_IMAGE:-anime-rss-service:acceptance-baseline}
RUN_ID=${RUN_ID:-$RANDOM-$$}
SOURCE_PROJECT="anime-rss-acceptance-source-$RUN_ID"
RESTORE_PROJECT="anime-rss-acceptance-restore-$RUN_ID"
BASE_PORT=${BASE_PORT:-$((20000 + $$ % 10000))}
SOURCE_PORT=$BASE_PORT
RESTORE_PORT=$((BASE_PORT + 1))
PASSWORD="acceptance-only-password"
TEMP_DIR=$(mktemp -d)
COOKIE_JAR="$TEMP_DIR/cookies.txt"
ARCHIVE="$TEMP_DIR/source.backup"

compose_for() {
  local project=$1 image=$2 port=$3
  shift 3
  ANIME_RSS_IMAGE="$image" ANIME_RSS_PORT="$port" \
    docker compose -p "$project" "$@"
}

cleanup() {
  compose_for "$SOURCE_PROJECT" "$CURRENT_IMAGE" "$SOURCE_PORT" down -v --remove-orphans >/dev/null 2>&1 || true
  compose_for "$RESTORE_PROJECT" "$CURRENT_IMAGE" "$RESTORE_PORT" down -v --remove-orphans >/dev/null 2>&1 || true
  docker volume rm -f "${SOURCE_PROJECT}_anime-rss-data" >/dev/null 2>&1 || true
  docker volume rm -f "${RESTORE_PROJECT}_anime-rss-data" >/dev/null 2>&1 || true
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

find_baseline() {
  if [[ -n "${BASELINE_REF:-}" ]]; then
    printf '%s\n' "$BASELINE_REF"
    return
  fi
  local candidate
  while read -r candidate; do
    if ! git cat-file -e "$candidate:migrations/versions/0012_event_observability.py" 2>/dev/null; then
      printf '%s\n' "$candidate"
      return
    fi
  done < <(git rev-list HEAD~1)
  return 1
}

wait_ready() {
  local port=$1
  local attempt
  for attempt in $(seq 1 90); do
    if curl -fsS "http://127.0.0.1:$port/api/v1/health/ready" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  return 1
}

csrf_token() {
  awk '$6 == "anime_rss_csrf" { value = $7 } END { print value }' "$COOKIE_JAR"
}

request_json() {
  local port=$1 method=$2 path=$3 data=${4:-}
  local args=(--fail --silent --show-error -b "$COOKIE_JAR" -c "$COOKIE_JAR" -X "$method")
  if [[ "$method" != "GET" ]]; then
    args+=(-H "X-CSRF-Token: $(csrf_token)")
  fi
  if [[ -n "$data" ]]; then
    args+=(-H "Content-Type: application/json" --data "$data")
  fi
  curl "${args[@]}" "http://127.0.0.1:$port$path"
}

login() {
  local port=$1
  rm -f "$COOKIE_JAR"
  curl --fail --silent --show-error -c "$COOKIE_JAR" \
    -H "Content-Type: application/json" \
    --data "{\"username\":\"admin\",\"password\":\"$PASSWORD\"}" \
    "http://127.0.0.1:$port/api/v1/auth/login" >/dev/null
}

assert_restored_state() {
  local port=$1
  request_json "$port" GET "/api/v1/system/settings" | jq -e '.setup_completed == true' >/dev/null
  request_json "$port" GET "/api/v1/subscriptions" | jq -e 'length == 1 and .[0].anime_title == "Acceptance Anime"' >/dev/null
  request_json "$port" GET "/api/v1/feeds" | jq -e 'length == 1 and .[0].name == "Acceptance Feed"' >/dev/null
  request_json "$port" GET "/api/v1/audit/events" | jq -e 'length > 0' >/dev/null
  request_json "$port" GET "/api/v1/operations/jobs" | jq -e 'any(.[]; .dedupe_key == "acceptance.lifecycle")' >/dev/null
  request_json "$port" GET "/api/v1/selection/decisions" | jq -e 'any(.[]; .id == "acceptance-decision")' >/dev/null
  request_json "$port" GET "/api/v1/downloads/tasks" | jq -e 'any(.[]; .id == "acceptance-task" and .decision_id == "acceptance-decision")' >/dev/null
}

seed_lifecycle_state() {
  local container_id=$1 feed_id=$2 subscription_id=$3
  docker cp "$ROOT/scripts/fixtures/seed-lifecycle.py" "$container_id:/tmp/seed-lifecycle.py" >/dev/null
  docker exec "$container_id" python /tmp/seed-lifecycle.py \
    /data/anime-rss.sqlite3 "$feed_id" "$subscription_id"
}

restore_volume() {
  local project=$1 image=$2
  local volume="${project}_anime-rss-data"
  docker volume create \
    --label "com.docker.compose.project=$project" \
    --label "com.docker.compose.volume=anime-rss-data" \
    "$volume" >/dev/null
  docker run --rm \
    -v "$volume:/data" \
    -v "$ARCHIVE:/restore.backup:ro" \
    "$image" anime-rss restore /restore.backup --data-dir /data >/dev/null
}

BASELINE_REF=$(find_baseline)
git archive --format=tar --output="$TEMP_DIR/baseline.tar" "$BASELINE_REF"
mkdir -p "$TEMP_DIR/baseline"
tar -xf "$TEMP_DIR/baseline.tar" -C "$TEMP_DIR/baseline"

printf 'Building baseline %s and current image...\n' "$BASELINE_REF"
docker build --quiet -t "$BASELINE_IMAGE" "$TEMP_DIR/baseline" >/dev/null
docker build --quiet -t "$CURRENT_IMAGE" . >/dev/null

printf 'Starting baseline Compose instance...\n'
compose_for "$SOURCE_PROJECT" "$BASELINE_IMAGE" "$SOURCE_PORT" up -d --no-build >/dev/null
wait_ready "$SOURCE_PORT"
curl -fsS "http://127.0.0.1:$SOURCE_PORT/" | grep -q '<div id="root"></div>'

curl --fail --silent --show-error -c "$COOKIE_JAR" \
  -H "Content-Type: application/json" \
  --data "{\"username\":\"admin\",\"password\":\"$PASSWORD\"}" \
  "http://127.0.0.1:$SOURCE_PORT/api/v1/auth/setup" >/dev/null

for step in administrator instance_preferences qbittorrent_connection download_defaults feed global_preferences subscription candidate_preview; do
  request_json "$SOURCE_PORT" POST "/api/v1/system/settings/setup/$step" >/dev/null
done

ANIME_ID=$(request_json "$SOURCE_PORT" POST "/api/v1/catalog/anime" '{"title":"Acceptance Anime"}' | jq -r '.id')
SUBSCRIPTION_ID=$(request_json "$SOURCE_PORT" POST "/api/v1/subscriptions" \
  "{\"anime_id\":\"$ANIME_ID\",\"rules\":{\"fallback_wait_minutes\":120}}" | jq -r '.id')
FEED_ID=$(request_json "$SOURCE_PORT" POST "/api/v1/feeds" \
  '{"name":"Acceptance Feed","url":"https://example.invalid/private.rss?token=acceptance"}' | jq -r '.id')
CONTAINER_ID=$(compose_for "$SOURCE_PROJECT" "$BASELINE_IMAGE" "$SOURCE_PORT" ps -q anime-rss)
seed_lifecycle_state "$CONTAINER_ID" "$FEED_ID" "$SUBSCRIPTION_ID"
assert_restored_state "$SOURCE_PORT"

BACKUP_NAME=$(request_json "$SOURCE_PORT" POST "/api/v1/system/backups" | jq -r '.filename')
docker cp "$CONTAINER_ID:/data/backups/$BACKUP_NAME" "$ARCHIVE" >/dev/null
test -s "$ARCHIVE"

printf 'Upgrading the existing volume to the current image...\n'
compose_for "$SOURCE_PROJECT" "$BASELINE_IMAGE" "$SOURCE_PORT" down >/dev/null
compose_for "$SOURCE_PROJECT" "$CURRENT_IMAGE" "$SOURCE_PORT" up -d --no-build >/dev/null
wait_ready "$SOURCE_PORT"
login "$SOURCE_PORT"
assert_restored_state "$SOURCE_PORT"

printf 'Restoring the backup into a clean current-image volume...\n'
restore_volume "$RESTORE_PROJECT" "$CURRENT_IMAGE"
compose_for "$RESTORE_PROJECT" "$CURRENT_IMAGE" "$RESTORE_PORT" up -d --no-build >/dev/null
wait_ready "$RESTORE_PORT"
login "$RESTORE_PORT"
assert_restored_state "$RESTORE_PORT"

printf 'Rolling back through the pre-upgrade backup...\n'
compose_for "$SOURCE_PROJECT" "$CURRENT_IMAGE" "$SOURCE_PORT" down -v >/dev/null
restore_volume "$SOURCE_PROJECT" "$BASELINE_IMAGE"
compose_for "$SOURCE_PROJECT" "$BASELINE_IMAGE" "$SOURCE_PORT" up -d --no-build >/dev/null
wait_ready "$SOURCE_PORT"
login "$SOURCE_PORT"
assert_restored_state "$SOURCE_PORT"

printf 'Compose acceptance passed: setup, backup, in-place upgrade, clean restore, and rollback.\n'
