"""python -m backend.reconstruction VIDEO OUT [--quick] [--train-steps N] [--memory-budget-gb G]
    [--watch-stdin]

Prints one JSON line per progress event (stage, state, step, total, message, seconds), which the
preparation queue (#137) reads. Run it again with the same OUT to continue a stopped run.
`--watch-stdin` stops the run when standard input closes: the web server starts it that way, so a
run never outlives the server that started it.
"""

import argparse
import json
import os
import sys
import threading
import traceback
from dataclasses import replace
from pathlib import Path

from backend.reconstruction.pipeline import Report, Settings, run_pipeline
from backend.reconstruction.splat import OutOfGpuMemory
from backend.reconstruction.stages import video_to_room

# About half the time and a little less sharp: fewer, smaller frames and less training.
QUICK = {"max_frames": 120, "long_side": 1280, "train_steps": 10_000}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.reconstruction")
    parser.add_argument("video", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--train-steps", type=int)
    parser.add_argument("--memory-budget-gb", type=float)
    parser.add_argument("--watch-stdin", action="store_true")
    args = parser.parse_args(argv)
    if args.watch_stdin:
        threading.Thread(target=stop_when_stdin_closes, daemon=True).start()
    settings = replace(Settings(), **QUICK) if args.quick else Settings()
    if args.train_steps:
        settings = replace(settings, train_steps=args.train_steps)
    if args.memory_budget_gb:
        settings = replace(settings, memory_budget_gb=args.memory_budget_gb)

    def progress(event: Report) -> None:
        print(json.dumps(event), flush=True)

    # A failure has already been printed as a `failed` event; the traceback goes to stderr.
    try:
        run_pipeline(video_to_room(args.video, args.out), args.out / "work", settings, progress)
    except OutOfGpuMemory:
        traceback.print_exc()
        return 3
    except Exception:
        traceback.print_exc()
        return 1
    return 0


def stop_when_stdin_closes() -> None:
    sys.stdin.read()
    os._exit(1)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
