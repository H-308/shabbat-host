"""The hand-written harness. One file per responsibility; every runtime action is printed with its file name."""
import os
import sys
from pathlib import Path

_QUIET = os.environ.get("HARNESS_QUIET") == "1"


def logger(file: str):
    name = Path(file).name

    def log(msg: str) -> None:
        if not _QUIET:
            print(f"[{name}] {msg}", file=sys.stderr, flush=True)

    return log
