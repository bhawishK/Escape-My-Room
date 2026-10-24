"""Turn room_splat.py (cells marked `# %%`) into room_splat.ipynb for Colab.

Markdown cells drop their `# ` prefixes; in code cells, lines written as `# !command` become
shell commands, so the .py file stays valid Python for checking.
"""

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    source = (HERE / "room_splat.py").read_text(encoding="utf-8")
    cells = []
    for chunk in re.split(r"^(?=# %%)", source, flags=re.MULTILINE):
        if not chunk.strip():
            continue
        marker, _, body = chunk.partition("\n")
        lines = body.strip("\n").split("\n")
        if "[markdown]" in marker:
            text = [re.sub(r"^# ?", "", line) for line in lines]
            cells.append({"cell_type": "markdown", "metadata": {}, "source": _lines(text)})
        else:
            code = [line[2:] if line.startswith("# !") else line for line in lines]
            cells.append(
                {
                    "cell_type": "code",
                    "metadata": {},
                    "execution_count": None,
                    "outputs": [],
                    "source": _lines(code),
                }
            )
    notebook = {
        "cells": cells,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"provenance": [], "gpuType": "T4"},
            "kernelspec": {"name": "python3", "display_name": "Python 3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }
    (HERE / "room_splat.ipynb").write_text(json.dumps(notebook, indent=1) + "\n", encoding="utf-8")


def _lines(lines: list[str]) -> list[str]:
    return [line + "\n" for line in lines[:-1]] + lines[-1:]


if __name__ == "__main__":
    main()
