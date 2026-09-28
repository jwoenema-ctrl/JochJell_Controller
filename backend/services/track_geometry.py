"""Shared cubic geometry for the visualizer and coordinate movement."""
from __future__ import annotations

from typing import Mapping, Sequence

XY = tuple[float, float]


def cubic_controls(points: Sequence[XY], index: int, section: Mapping) -> tuple[XY, XY]:
    start, end = points[index:index + 2]
    if len(points) == 2:
        middle = (start[0] + end[0]) / 2
        first, second = (middle, start[1]), (middle, end[1])
    else:
        previous = points[max(0, index - 1)]
        following = points[min(len(points) - 1, index + 2)]
        first = tuple(start[axis] + (end[axis] - previous[axis]) / 6 for axis in (0, 1))
        second = tuple(end[axis] - (following[axis] - start[axis]) / 6 for axis in (0, 1))
    if section.get("control1") is not None:
        offset = section["control1"]
        first = (start[0] + float(offset["x"]), start[1] + float(offset["y"]))
    if section.get("control2") is not None:
        offset = section["control2"]
        second = (end[0] + float(offset["x"]), end[1] + float(offset["y"]))
    return first, second


def cubic_point(start: XY, first: XY, second: XY, end: XY, amount: float) -> XY:
    u, v = amount, 1 - amount
    return tuple(v ** 3 * start[axis] + 3 * v ** 2 * u * first[axis]
                 + 3 * v * u ** 2 * second[axis] + u ** 3 * end[axis] for axis in (0, 1))


def sample_track(points: Sequence[XY], edge: Mapping) -> tuple[XY, ...]:
    """Sample the same 32 subdivisions used by the browser.

    Edges without cubic metadata retain their legacy polyline geometry.
    """
    sections = edge.get("bezier_segments")
    if not isinstance(sections, (list, tuple)):
        return tuple(points)
    samples: list[XY] = []
    for index in range(len(points) - 1):
        first, second = cubic_controls(points, index, sections[index] if index < len(sections) else {})
        for step in range(0 if index == 0 else 1, 33):
            samples.append(cubic_point(points[index], first, second, points[index + 1], step / 32))
    return tuple(samples)
