#!/usr/bin/env bash
# Wrapper script for daily lead scraper + Slack notification.
# Works both locally and on cloud runtimes (e.g. Render cron).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Use local venv when available (local dev), otherwise system Python (cloud).
if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/venv/bin/activate"
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

# Run the scraper and capture results
"$PYTHON_BIN" run_agent.py 2>&1 | tee -a "$SCRIPT_DIR/agent.log"

# Send Slack notification
"$PYTHON_BIN" notify_slack.py 2>&1 | tee -a "$SCRIPT_DIR/agent.log"
