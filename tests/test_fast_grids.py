"""#72: the numpy outline and edge checks give exactly what the per-pixel loops gave."""

from __future__ import annotations

import random

from pagan.asset import _edge_pixel, _edge_pixel_slow, _outline, _outline_slow

KEYS = "..........0129aZéλ"


def _grid(rng: random.Random, width: int, height: int, fill: float) -> tuple[str, ...]:
    return tuple("".join(rng.choice(KEYS[10:]) if rng.random() < fill else "." for _ in range(width)) for _ in range(height))


def test_outline_and_edge_match_the_reference_loops() -> None:
    rng = random.Random(72)
    for _ in range(400):
        width, height = rng.randint(1, 12), rng.randint(1, 12)
        grid = _grid(rng, width, height, rng.choice([0.0, 0.05, 0.3, 0.9, 1.0]))
        ignore = frozenset(rng.sample("0129aZéλ", rng.randint(0, 2)))
        colour = rng.choice("0λ")
        assert _outline(grid, colour, ignore) == _outline_slow(grid, colour, ignore), (grid, ignore)
        margin = rng.randint(0, 7)
        assert _edge_pixel(grid, margin, ignore) == _edge_pixel_slow(grid, margin, ignore), (grid, margin, ignore)


def test_empty_and_ragged_grids_take_the_plain_path() -> None:
    assert _outline((), "0") == () and _edge_pixel(()) is None
    ragged = ("a..", "a")
    assert _edge_pixel(ragged) == _edge_pixel_slow(ragged) == (0, 0)
