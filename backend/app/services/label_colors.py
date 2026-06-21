from __future__ import annotations

import random
import re
from math import sqrt


MIN_LABEL_COLOR_DISTANCE = 60.0
LABEL_COLOR_PALETTE = [
    "#ff7a1a",
    "#1f9fe5",
    "#22c55e",
    "#a855f7",
    "#ef4444",
    "#eab308",
    "#14b8a6",
    "#ec4899",
    "#6366f1",
    "#84cc16",
    "#f97316",
    "#06b6d4",
    "#8b5cf6",
    "#f43f5e",
    "#10b981",
    "#64748b",
]

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


def normalize_hex_color(color: str | None) -> str | None:
    if not color:
        return None
    match = _HEX_RE.match(color.strip())
    if match is None:
        return None
    return f"#{match.group(1).lower()}"


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    normalized = normalize_hex_color(color)
    if normalized is None:
        raise ValueError(f"Invalid hex color: {color}")
    return (
        int(normalized[1:3], 16),
        int(normalized[3:5], 16),
        int(normalized[5:7], 16),
    )


def color_distance(color1: str, color2: str) -> float:
    r1, g1, b1 = hex_to_rgb(color1)
    r2, g2, b2 = hex_to_rgb(color2)
    return sqrt((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2)


def is_color_conflict(color: str, used_colors: list[str] | set[str]) -> bool:
    normalized = normalize_hex_color(color)
    if normalized is None:
        return True
    for used_color in used_colors:
        normalized_used = normalize_hex_color(used_color)
        if normalized_used is None:
            continue
        if color_distance(normalized, normalized_used) < MIN_LABEL_COLOR_DISTANCE:
            return True
    return False


def pick_distinct_label_color(preferred_color: str | None, used_colors: list[str] | set[str]) -> str:
    normalized_preferred = normalize_hex_color(preferred_color)
    if normalized_preferred is not None and not is_color_conflict(normalized_preferred, used_colors):
        return normalized_preferred

    for color in LABEL_COLOR_PALETTE:
        if not is_color_conflict(color, used_colors):
            return color

    for _ in range(128):
        candidate = f"#{random.randint(0, 0xFFFFFF):06x}"
        if not is_color_conflict(candidate, used_colors):
            return candidate

    return f"#{random.randint(0, 0xFFFFFF):06x}"
