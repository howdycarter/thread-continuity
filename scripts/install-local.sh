#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${THREAD_CONTINUITY_VENV:-"$HOME/.thread-continuity/venv"}"
BIN_DIR="${THREAD_CONTINUITY_BIN_DIR:-"$HOME/.local/bin"}"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: scripts/install-local.sh [--dry-run]

Installs Thread Continuity as a local CLI plus MCP server:
  thread-continuity
  thread-continuity-mcp

Environment overrides:
  THREAD_CONTINUITY_VENV     default: ~/.thread-continuity/venv
  THREAD_CONTINUITY_BIN_DIR  default: ~/.local/bin
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '+'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

echo "Thread Continuity local install"
echo "Repo: $ROOT_DIR"
echo "Venv: $VENV_DIR"
echo "Bin:  $BIN_DIR"

run python3 -m venv "$VENV_DIR"
run "$VENV_DIR/bin/python" -m pip install -e "$ROOT_DIR"
run mkdir -p "$BIN_DIR"
run ln -sf "$VENV_DIR/bin/thread-continuity" "$BIN_DIR/thread-continuity"
run ln -sf "$VENV_DIR/bin/thread-continuity-mcp" "$BIN_DIR/thread-continuity-mcp"

cat <<EOF

Installed commands:
  $BIN_DIR/thread-continuity
  $BIN_DIR/thread-continuity-mcp

Next:
  thread-continuity doctor
  thread-continuity mcp-config --mode installed
  thread-continuity index
  thread-continuity resume "building X"

If your shell cannot find the command, add this to PATH:
  export PATH="$BIN_DIR:\$PATH"
EOF
