"""Optional isolated PostgreSQL tests: run with Python 3.12 and pgserver, not the app venv."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pgserver

root = Path(__file__).resolve().parents[1]
data = tempfile.mkdtemp(prefix="pppg-", dir="/tmp")
server = pgserver.get_server(data, cleanup_mode="delete")
try:
    env = {**os.environ, "TEST_DATABASE_URL": server.get_uri()}
    completed = subprocess.run(
        [str(root / ".venv/bin/python"), "-m", "pytest", *sys.argv[1:]], cwd=root, env=env
    )
    raise SystemExit(completed.returncode)
finally:
    server.cleanup()
