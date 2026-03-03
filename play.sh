#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}"
DOTENV_PATH="${REPO_ROOT}/.env"

if [[ -f "${DOTENV_PATH}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${DOTENV_PATH}"
  set +a
  echo "[play.sh] Loaded environment from ${DOTENV_PATH}"
else
  echo "[play.sh] No .env found at ${DOTENV_PATH}; using current shell environment."
fi

if [[ -n "${LLM_API_KEY:-}" ]]; then
  echo "[play.sh] LLM_API_KEY detected; launching with real LLM API."
else
  echo "[play.sh] LLM_API_KEY is not set; launching without real LLM (simulated fallback)."
fi

GODOT_BIN="${GODOT_PATH:-godot}"
echo "[play.sh] Launch command: ${GODOT_BIN} --path godot"
"${GODOT_BIN}" --path godot
