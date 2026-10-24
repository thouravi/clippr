"""One JSON object per line on stdout. The desktop shell forwards these."""

from __future__ import annotations

import json
import sys


def _out(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def progress(stage: str, message: str, percent: float | None = None) -> None:
    payload: dict = {"type": "progress", "stage": stage, "message": message}
    if percent is not None:
        payload["percent"] = round(percent, 1)
    _out(payload)


def result(data: dict) -> None:
    _out({"type": "result", "ok": True, "data": data})


def fail(message: str, code: int = 1) -> None:
    _out({"type": "result", "ok": False, "error": message})
    raise SystemExit(code)
