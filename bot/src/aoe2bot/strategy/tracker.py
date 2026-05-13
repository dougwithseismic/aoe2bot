"""Action state tracker — prevents duplicate actions and tracks what's in progress.

Solves: building a second lumber camp because we don't know one is already going up,
training vils when TC is already queued, etc.
"""

from __future__ import annotations

import time
import logging

logger = logging.getLogger(__name__)

# How long before an action is considered stale (seconds of game time)
_ACTION_TTL = 60.0


class ActionTracker:
    """Tracks in-progress actions to prevent duplicates."""

    def __init__(self) -> None:
        self._active: dict[str, float] = {}

    def start(self, key: str, game_time: float) -> None:
        """Mark an action as in progress."""
        self._active[key] = game_time

    def is_active(self, key: str, game_time: float) -> bool:
        """Check if an action is currently in progress (and not stale)."""
        started = self._active.get(key)
        if started is None:
            return False
        if game_time - started > _ACTION_TTL:
            del self._active[key]
            return False
        return True

    def complete(self, key: str) -> None:
        """Mark an action as done."""
        self._active.pop(key, None)

    def clear(self) -> None:
        self._active.clear()


class ScoutPlanner:
    """Plans a scouting path around the base to reveal resources.

    Sends the scout (or a vil) in a circle around TC at increasing radii
    to reveal trees, gold, stone, berries.
    """

    def __init__(self) -> None:
        self._waypoints: list[tuple[float, float]] = []
        self._current_idx = 0
        self._initialized = False
        self._scout_unit_id: int | None = None
        self._complete = False

    @property
    def is_complete(self) -> bool:
        return self._complete

    def init_waypoints(self, base_x: float, base_y: float) -> None:
        """Generate scouting waypoints in expanding circles around base."""
        if self._initialized:
            return
        self._initialized = True

        import math
        # Inner ring (radius 10) — find nearby resources
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            self._waypoints.append((
                base_x + 10 * math.cos(rad),
                base_y + 10 * math.sin(rad),
            ))
        # Outer ring (radius 20) — find distant resources
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            self._waypoints.append((
                base_x + 20 * math.cos(rad),
                base_y + 20 * math.sin(rad),
            ))

    def get_next_waypoint(self) -> tuple[float, float] | None:
        """Get the next scouting waypoint, or None if done."""
        if self._current_idx >= len(self._waypoints):
            self._complete = True
            return None
        wp = self._waypoints[self._current_idx]
        self._current_idx += 1
        return wp

    def set_scout_id(self, unit_id: int) -> None:
        self._scout_unit_id = unit_id

    @property
    def scout_id(self) -> int | None:
        return self._scout_unit_id
