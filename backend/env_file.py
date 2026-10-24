"""Read settings and keys from a `.env` file so they need not be typed before every start.

The file holds `NAME=value` lines; blank lines and `#` comments are skipped, and a value may be
wrapped in quotes or preceded by `export`. A variable already set in the environment wins, so a
one-off `set NAME=...` still overrides the file. `ESCAPE_ROOM_ENV_FILE` names another file, or
none when empty; the default is `.env` at the repository root.
"""

import os
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]


def load_env_file() -> None:
    chosen = os.environ.get("ESCAPE_ROOM_ENV_FILE")
    if chosen == "":
        return
    path = Path(chosen) if chosen else REPOSITORY / ".env"
    if not path.is_file():
        if chosen:
            raise FileNotFoundError(f"ESCAPE_ROOM_ENV_FILE names {path}, which does not exist.")
        return
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, equals, value = line.removeprefix("export ").partition("=")
        name, value = name.strip(), value.strip()
        if not equals or not name:
            raise ValueError(f"{path}, line {number}: expected NAME=value.")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(name, value)
