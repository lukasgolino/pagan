"""Progress lines on stderr for slow steps (model renders, Godot), so a long run shows it's alive.

Only the CLI turns them on (`--quiet` or PAGAN_QUIET=1 turns them off); stdout, and so `--json`, is never touched.
"""

from __future__ import annotations

import sys

enabled = False


def note(message: str) -> None:
    if enabled:
        print(f"pagan: {message}", file=sys.stderr, flush=True)
