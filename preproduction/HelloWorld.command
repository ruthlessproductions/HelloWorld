#!/bin/zsh
# Double-click in Finder to open the HelloWorld app in your browser (http://localhost:8765).
# The first run sets up the Python environment; keep this window open while you work.
set -e
cd "${0:A:h}"

if [[ ! -x .venv/bin/helloworld ]]; then
  echo "Setting up HelloWorld (first run only)..."
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -e .
fi

exec .venv/bin/helloworld app "$@"
