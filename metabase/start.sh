#!/bin/zsh
# Start Metabase locally in Docker, with the DuckDB driver and the published warehouse.
#
# Run from the repository root:  zsh metabase/start.sh
#
# What gets mounted:
#   plugins/   the DuckDB driver jar — Metabase loads any driver it finds here at startup
#   data/      the published copy of the warehouse (scripts/publish_warehouse_for_metabase.py)
#   app-data/  Metabase's own storage, so saved questions and dashboards survive a restart
#
# The data folder is mounted read-only. Metabase has no reason to write to the warehouse,
# and a reporting tool that cannot write to its source cannot corrupt it.

set -eu

ROOT="${0:A:h:h}"
NAME="events-coverage-metabase"
IMAGE="events-coverage-metabase:local"
PORT=3000

mkdir -p "$ROOT/metabase/app-data"

# Built locally rather than pulled, because the official Metabase image cannot run the
# DuckDB driver — see metabase/Dockerfile for why.
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building $IMAGE (first run only) ..."
  docker build -t "$IMAGE" -f "$ROOT/metabase/Dockerfile" "$ROOT/metabase"
fi

if [ ! -f "$ROOT/metabase/plugins/duckdb.metabase-driver.jar" ]; then
  echo "Missing metabase/plugins/duckdb.metabase-driver.jar."
  echo "Download it from the release listed in metabase/README.md, then run this again."
  exit 1
fi

if [ ! -f "$ROOT/metabase/data/events.duckdb" ]; then
  echo "Missing metabase/data/events.duckdb."
  echo "Run: .venv/bin/python scripts/publish_warehouse_for_metabase.py"
  exit 1
fi

docker rm -f "$NAME" >/dev/null 2>&1 || true

docker run -d --name "$NAME" \
  -p "$PORT:3000" \
  -v "$ROOT/metabase/data:/data:ro" \
  -v "$ROOT/metabase/app-data:/home/metabase/app-data" \
  "$IMAGE" >/dev/null

echo "Starting $NAME on http://localhost:$PORT"
echo "First start takes a minute or two while Metabase builds its own storage."
echo "Follow it with:  docker logs -f $NAME"
