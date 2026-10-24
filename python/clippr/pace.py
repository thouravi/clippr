"""Skip the quiet stretch between kills while a highlight is recorded.

A multi-kill can run for most of a minute even though each fight is short.
The capture keeps a couple of seconds after a kill and a couple of seconds
before the next one, and jumps the demo across the rest.
"""

from __future__ import annotations

HOLD_AFTER_SECONDS = 2.0
APPROACH_SECONDS = 2.0
MIN_SKIP_SECONDS = 1.5


def between_kill_cuts(
    kill_ticks: list[int],
    tickrate: float,
    start: int | None = None,
    end: int | None = None,
) -> list[tuple[int, int]]:
    """Return (leave, arrive) demo ticks. The recording jumps from leave to arrive."""
    rate = tickrate if tickrate >= 16 else 64.0
    hold = max(1, int(round(HOLD_AFTER_SECONDS * rate)))
    approach = max(1, int(round(APPROACH_SECONDS * rate)))
    minimum = max(1, int(round(MIN_SKIP_SECONDS * rate)))
    ticks = sorted({int(tick) for tick in kill_ticks if int(tick) > 0})
    cuts: list[tuple[int, int]] = []
    for earlier, later in zip(ticks, ticks[1:]):
        leave = earlier + hold
        arrive = later - approach
        if arrive - leave < minimum:
            continue
        if start is not None and leave <= start:
            continue
        if end is not None and arrive >= end:
            continue
        cuts.append((leave, arrive))
    return cuts


def skipped_seconds(kill_ticks: list[int], tickrate: float) -> float:
    rate = tickrate if tickrate >= 16 else 64.0
    return sum(arrive - leave for leave, arrive in between_kill_cuts(kill_ticks, rate)) / rate
