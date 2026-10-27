#!/bin/bash
# Pharma Raw-Material Intelligence Platform automatic update job (Component D).
#   1. discover   - look for NEW documents on watched pages (+ web search if BRAVE_API_KEY is set)
#   2. check      - re-download every known source; changed ones are saved as new versions
#                   and changed EC PDFs are re-extracted into data/staging/ for review
#   3. ingest     - load any rows you have approved (Y) and rebuild product links
#   4. demand     - recalculate raw-material demand
# Nothing is approved automatically: new facts always wait for your Y.
# Run by hand:  ./run_update.sh          Schedule weekly:  ./install_schedule.sh
cd "$(dirname "$0")" || exit 1
mkdir -p logs
PY="./venv/bin/python3"
[ -x "$PY" ] || PY="python3"
{
  echo "==== Pharma Raw-Material Intelligence Platform update $(date '+%Y-%m-%d %H:%M') ===="
  echo "--- 1. discover new documents"; "$PY" src/discover.py
  echo "--- 2. check known sources for changes"; "$PY" src/download.py --check
  echo "--- 3. load approved rows"; "$PY" src/ingest.py
  echo "--- 4. recalculate demand"; "$PY" src/demand.py
  echo "==== done ===="
} 2>&1 | tee -a logs/update.log
