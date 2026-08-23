#!/usr/bin/env bash
# Bash development helper (development on WSL/Linux; production is native Windows).
set -euo pipefail

VENV=".venv"

case "${1:-help}" in
  setup)
    python3 -m venv --without-pip "$VENV" 2>/dev/null || true
    curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
    "$VENV/bin/python" /tmp/get-pip.py -q
    "$VENV/bin/pip" install -q -e '.[dev]'
    ;;
  lint)   "$VENV/bin/ruff" check src tests ;;
  format) "$VENV/bin/ruff" check src tests --fix ;;
  types)  "$VENV/bin/mypy" ;;
  test)   "$VENV/bin/python" -m pytest -q ${2:-} ;;
  live)   "$VENV/bin/python" -m pytest -q -m live ;;
  run)    "$VENV/bin/opdisc" run "${@:2}" ;;
  audit)  "$VENV/bin/opdisc" audit . ;;
  build)  "$VENV/bin/python" -m build ;;
  *)
    echo "usage: scripts/dev.sh {setup|lint|format|types|test|live|run|audit|build}"
    ;;
esac
