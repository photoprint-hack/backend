"""Export the production API schema without opening a database connection."""

import argparse
import json
import os
import secrets
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Exporting a schema must not require or expose a deploy secret.
os.environ["APP_ENV"] = "production"
project = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())["project"]
os.environ["APP_NAME"] = project["name"]
os.environ["APP_VERSION"] = project["version"]
os.environ["JWT_SECRET_KEY"] = secrets.token_urlsafe(48)
os.environ["COOKIE_SECURE"] = "true"
os.environ["COOKIE_SAMESITE"] = "none"
os.environ["FRONTEND_URL"] = "https://frontend.example.invalid"
os.environ["BACKEND_URL"] = "https://backend.example.invalid"

from app.main import app  # noqa: E402 -- Settings must see the export environment before app import.

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("openapi.json"))
    args = parser.parse_args()
    args.output.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n")
    print("OpenAPI written:", args.output)
