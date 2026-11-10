"""Find DATABASE_URL in the repo's .env when it is not already in the environment.

WHY THIS EXISTS. On GitHub Actions the connection string arrives as a job environment variable, and
every script reads it from there. On a laptop it lives in a gitignored `.env`, and until now every
script had to be launched behind a shell command that set the variable first:

    $env:DATABASE_URL = ((Select-String -Path .env -Pattern '^DATABASE_URL=').Line).Substring(13).Trim()
    .venv\\Scripts\\python.exe -X utf8 scripts/whatever.py

That is two commands joined by a newline, and a reviewer agent's shell permission allowlist matches one
command at a time, so the whole thing is refused. On 2026-11-10 that is exactly why two review sessions
could inspect files and run nothing. Reading `.env` here makes a single plain command sufficient:

    .venv\\Scripts\\python.exe -X utf8 scripts/whatever.py

PRECEDENCE. An already-set variable always wins. A workflow's secret must never be overridden by a file
that happens to be lying around.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = ".env"
KEY = "DATABASE_URL"


def load_env_file(path: str | Path = ENV_FILE) -> str | None:
    """Return the DATABASE_URL from `path`, or None if the file or the key is absent."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == KEY:
            return value.strip().strip("\"'")
    return None


def ensure_database_url(path: str | Path = ENV_FILE) -> str | None:
    """Set DATABASE_URL from `path` if it is unset, and return whatever is now in the environment."""
    current = os.environ.get(KEY)
    if current:
        return current
    found = load_env_file(path)
    if found:
        os.environ[KEY] = found
    return found
