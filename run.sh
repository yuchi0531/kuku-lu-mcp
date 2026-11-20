#!/bin/sh
# Launch the m.kuku.lu MCP server over stdio with an isolated interpreter.
# Hermes/Claude Desktop may export a PYTHONPATH that shadows the venv,
# so clear it before exec.
set -eu
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
unset PYTHONPATH PYTHONHOME
cd "$DIR"
PYTHONPATH="$DIR" exec "$DIR/.venv/bin/python" -m kukulumcp.server "$@"
