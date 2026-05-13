"""Map exploration tracking and resource discovery/depletion."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .spatial import Position


@dataclass
class KnownResource:
    id: int
    resource_type: str
    position: Position
    first_seen: float
    last_seen: float
    depleted: bool = False


# 8 compass directions as (dx, dy) offsets.
_DIRECTIONS = [
    Position(0, -1),   # N
    Position(1, -1),   # NE
    Position(1, 0),    # E
    Position(1, 1),    # SE
    Position(0, 1),    # S
    Position(-1, 1),   # SW
    Position(-1, 0),   # W
    Position(-1, -1),  # NW
]


class MapKnowledge:
    """Tracks explored tiles (4x4 grid cells) and known resources."""

    def __init__(self, width: int = 200, height: int = 200) -> None:
        self.width = width
        self.height = height
        self._explored: set[tuple[int, int]] = set()
        self._resources: dict[str, dict[int, KnownResource]] = {}
        self._last_scan_ids: dict[str, set[int]] = {}

    # ── Grid helpers ──

    @staticmethod
    def _to_grid(x: float, y: float) -> tuple[int, int]:
        return int(x) // 4, int(y) // 4

    @property
    def _grid_w(self) -> int:
        return max(1, self.width // 4)

    @property
    def _grid_h(self) -> int:
        return max(1, self.height // 4)

    # ── Core update ──

    def update(
        self,
        scan: dict | None,
        unit_positions: list[Position],
        game_time: float,
    ) -> None:
        for pos in unit_positions:
            self.mark_explored(pos)

        if scan is None:
            return

        for res_type in ("trees", "gold", "stone", "forage"):
            objects = scan.get(res_type, [])
            current_ids: set[int] = set()
            type_dict = self._resources.setdefault(res_type, {})

            for obj in objects:
                rid = obj["id"]
                current_ids.add(rid)
                if rid in type_dict:
                    type_dict[rid].last_seen = game_time
                    type_dict[rid].depleted = False
                else:
                    type_dict[rid] = KnownResource(
                        id=rid,
                        resource_type=res_type,
                        position=Position(obj["x"], obj["y"]),
                        first_seen=game_time,
                        last_seen=game_time,
                    )

            prev_ids = self._last_scan_ids.get(res_type, set())
            for rid in prev_ids - current_ids:
                if rid in type_dict:
                    type_dict[rid].depleted = True

            self._last_scan_ids[res_type] = current_ids

    # ── Exploration ──

    def mark_explored(self, pos: Position, radius: float = 8.0) -> None:
        grid_radius = max(1, int(radius / 4))
        cx, cy = self._to_grid(pos.x, pos.y)
        for dx in range(-grid_radius, grid_radius + 1):
            for dy in range(-grid_radius, grid_radius + 1):
                if dx * dx + dy * dy <= grid_radius * grid_radius:
                    gx, gy = cx + dx, cy + dy
                    if 0 <= gx < self._grid_w and 0 <= gy < self._grid_h:
                        self._explored.add((gx, gy))

    def is_explored(self, pos: Position) -> bool:
        return self._to_grid(pos.x, pos.y) in self._explored

    def get_unexplored_direction(self, from_pos: Position) -> Position | None:
        cx, cy = self._to_grid(from_pos.x, from_pos.y)
        probe_dist = 5  # grid cells to check in each direction
        best_dir: Position | None = None
        best_unexplored = -1

        for d in _DIRECTIONS:
            unexplored = 0
            for step in range(1, probe_dist + 1):
                gx = cx + int(d.x) * step
                gy = cy + int(d.y) * step
                if 0 <= gx < self._grid_w and 0 <= gy < self._grid_h:
                    if (gx, gy) not in self._explored:
                        unexplored += 1
            if unexplored > best_unexplored:
                best_unexplored = unexplored
                best_dir = d

        if best_unexplored <= 0:
            return None
        return best_dir

    def get_exploration_pct(self, center: Position, radius: float) -> float:
        grid_radius = max(1, int(radius / 4))
        cx, cy = self._to_grid(center.x, center.y)
        total = 0
        explored = 0
        for dx in range(-grid_radius, grid_radius + 1):
            for dy in range(-grid_radius, grid_radius + 1):
                if dx * dx + dy * dy <= grid_radius * grid_radius:
                    gx, gy = cx + dx, cy + dy
                    if 0 <= gx < self._grid_w and 0 <= gy < self._grid_h:
                        total += 1
                        if (gx, gy) in self._explored:
                            explored += 1
        if total == 0:
            return 1.0
        return explored / total

    # ── Resources ──

    def get_resources(self, resource_type: str) -> list[KnownResource]:
        type_dict = self._resources.get(resource_type, {})
        return [r for r in type_dict.values() if not r.depleted]

    def get_nearest_resource(
        self, resource_type: str, to: Position
    ) -> KnownResource | None:
        best: KnownResource | None = None
        best_dist = float("inf")
        for r in self.get_resources(resource_type):
            d = to.distance_to(r.position)
            if d < best_dist:
                best_dist = d
                best = r
        return best

    def has_discovered(self, resource_type: str) -> bool:
        return len(self.get_resources(resource_type)) > 0
