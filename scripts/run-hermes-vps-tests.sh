#!/usr/bin/env bash
# Explicit VPS-only rehearsal. No production connections, polling or deployment.
set -euo pipefail

candidate_dir="${1:?Pass the exported candidate directory}"
case "$candidate_dir" in
  /opt/benka-hermes/candidates/*) ;;
  *) echo 'Expected an isolated /opt/benka-hermes/candidates directory' >&2; exit 2 ;;
esac
cd "$candidate_dir"
test -f CANDIDATE_TREE
revision="$(tr -d '\n' < CANDIDATE_TREE)"
test "${#revision}" -eq 40
report_dir="/opt/benka-hermes/reports/$revision"
mkdir -p "$report_dir"
chmod 700 "$report_dir"
trap 'result=$?; echo "$result" > "$report_dir/exit-code"' EXIT
runtime_image="benka-hermes:runtime-$revision"
test_image="benka-hermes:test-$revision"

# Provision the separate benka-migration builder with 2 CPU / 4 GiB first.
docker buildx build --builder benka-migration --load --target runtime \
  -f deploy/hermes/Dockerfile -t "$runtime_image" .
docker buildx build --builder benka-migration --load --target test \
  -f deploy/hermes/Dockerfile -t "$test_image" .
docker image inspect --format '{{.Id}}' "$runtime_image" > "$report_dir/runtime-image-id"
docker image inspect --format '{{.Id}}' "$test_image" > "$report_dir/test-image-id"

limits=(--rm --network none --read-only --tmpfs /tmp:size=256m,mode=1777
        --memory 2g --cpus 2 --pids-limit 256 --cap-drop ALL --security-opt no-new-privileges:true)
docker run "${limits[@]}" "$test_image" > "$report_dir/regressions.log" 2>&1
docker run "${limits[@]}" --entrypoint python "$test_image" \
  /opt/benka/scripts/verify-hermes-contract.py > "$report_dir/native-contract.log" 2>&1
docker run "${limits[@]}" --entrypoint python \
  --mount "type=bind,src=$candidate_dir/scripts/verify-hermes-claw-vps.py,dst=/run/benka/verify-claw.py,readonly" \
  "$runtime_image" /run/benka/verify-claw.py > "$report_dir/native-claw.log" 2>&1
docker run "${limits[@]}" \
  --mount "type=bind,src=$candidate_dir/deploy/hermes/manifest.standby.example.json,dst=/run/benka/manifest.json,readonly" \
  --entrypoint benka "$runtime_image" status > "$report_dir/standby.json"
docker compose -f deploy/hermes/compose.yaml config --quiet
test_network="benka-test-${revision:0:12}"
test_volume="benka-test-${revision:0:12}"
test_redis="benka-test-redis-${revision:0:12}"
cleanup() {
  result=$?
  docker rm -f "$test_redis" >/dev/null 2>&1 || true
  docker network rm "$test_network" >/dev/null 2>&1 || true
  docker volume rm "$test_volume" >/dev/null 2>&1 || true
  echo "$result" > "$report_dir/exit-code"
}
# Resources are exclusively created by this run, never existing production names.
docker network inspect "$test_network" >/dev/null 2>&1 && exit 2
docker volume inspect "$test_volume" >/dev/null 2>&1 && exit 2
docker network create --internal "$test_network" >/dev/null
docker volume create "$test_volume" >/dev/null
trap cleanup EXIT
docker run -d --name "$test_redis" --network "$test_network" --network-alias redis \
  --memory 256m --cpus 1 --mount "type=volume,src=$test_volume,dst=/data" \
  redis:7.4@sha256:71da9275c5f3fcb97d0fa0c8c5b36cc995327265420f17a04bfd544f458059f7 \
  redis-server --appendonly yes --appendfsync always >/dev/null
redis_check() {
  docker run --rm --network "$test_network" --read-only --tmpfs /tmp:size=128m \
    --memory 512m --cpus 1 --cap-drop ALL --security-opt no-new-privileges:true \
    --entrypoint python "$test_image" /opt/benka/scripts/verify-redis-vps.py "$1"
}
redis_check prepare > "$report_dir/redis.log" 2>&1
docker restart "$test_redis" >/dev/null
redis_check verify >> "$report_dir/redis.log" 2>&1
echo "PASS: VPS image build, regressions, native contract and offline standby; tree $revision"
