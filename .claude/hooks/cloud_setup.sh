#!/usr/bin/env bash
# SessionStart hook. A cloud thread of the owner's Claude Project starts from a fresh clone without .venv or a dbt
# manifest: sync the venv from uv.lock (a no-op when nothing changed) and parse the dbt project, so pytest and the
# Dagster definitions can load. Does nothing on the owner's Mac. Python 3.12 comes from the environment's setup
# script (uv python install 3.12).
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}" || exit 0

log=/tmp/events_cloud_setup.log
{
  uv sync -q --python 3.12 &&
    (cd dbt && ../.venv/bin/dbt parse -q)
} >"$log" 2>&1 || echo "events_coverage cloud setup failed (uv sync or dbt parse), see $log"
exit 0
