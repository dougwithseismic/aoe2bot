"""Spatial awareness and building placement — the foundation layer.

Understands the map, base layout, resource locations, and provides
smart placement decisions for any building type.
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..controller import GameController

logger = logging.getLogger(__name__)


class PlacementGoal(Enum):
    NEAR_TC = auto()
    NEAR_RESOURCES = auto()
    WALL_EDGE = auto()
    FARM_RING = auto()
    TIGHT_CLUSTER = auto()
    DEFENSIVE_PERIMETER = auto()


@dataclass
class Position:
    x: float
    y: float

    def distance_to(self, other: Position) -> float:
        return math.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)

    def offset(self, dx: float, dy: float) -> Position:
        return Position(self.x + dx, self.y + dy)

    def direction_to(self, other: Position) -> Position:
        """Unit vector pointing from self toward other."""
        d = self.distance_to(other)
        if d < 0.01:
            return Position(0, 0)
        return Position((other.x - self.x) / d, (other.y - self.y) / d)

    def __repr__(self) -> str:
        return f"({self.x:.0f},{self.y:.0f})"


@dataclass
class ResourceCluster:
    resource_type: str
    objects: list[dict]
    center: Position
    count: int

    @classmethod
    def from_objects(cls, resource_type: str, objects: list[dict]) -> ResourceCluster:
        if not objects:
            return cls(resource_type=resource_type, objects=[], center=Position(0, 0), count=0)
        xs = [o["x"] for o in objects]
        ys = [o["y"] for o in objects]
        return cls(
            resource_type=resource_type,
            objects=objects,
            center=Position(sum(xs) / len(xs), sum(ys) / len(ys)),
            count=len(objects),
        )


@dataclass
class BaseLayout:
    """Represents the current understanding of our base."""
    tc_pos: Position | None = None
    map_width: int = 0
    map_height: int = 0
    buildings: list[dict] = field(default_factory=list)
    resources: dict[str, ResourceCluster] = field(default_factory=dict)
    _placement_history: list[Position] = field(default_factory=list)

    @property
    def map_center(self) -> Position:
        return Position(self.map_width / 2, self.map_height / 2)

    @property
    def base_center(self) -> Position:
        return self.tc_pos or self.map_center

    def edge_direction(self) -> Position:
        """Direction from map center toward our base — tells us which map edge we're near."""
        bc = self.base_center
        mc = self.map_center
        return mc.direction_to(bc)

    def defensive_side(self) -> Position:
        """Direction toward map center (where enemies likely are)."""
        bc = self.base_center
        mc = self.map_center
        return bc.direction_to(mc)

    def safe_side(self) -> Position:
        """Direction away from map center (toward our corner/edge)."""
        d = self.defensive_side()
        return Position(-d.x, -d.y)


class SpatialEngine:
    """
    Maintains spatial awareness of the map and provides placement decisions.

    Call refresh() each tick (or every few ticks) to update state.
    Then use find_placement() to get smart building positions.
    """

    def __init__(self, ctrl: GameController):
        self.ctrl = ctrl
        self.layout = BaseLayout()
        self._tile_cache: dict[tuple[int, int], dict] = {}
        self._last_refresh = 0.0

    def refresh(self, raw_state: dict) -> None:
        """Update spatial state from enriched game state."""
        game_time = raw_state.get("time", 0)
        if game_time - self._last_refresh < 3.0:
            return
        self._last_refresh = game_time

        # TC position
        tcs = raw_state.get("_tcs", [])
        if tcs:
            self.layout.tc_pos = Position(tcs[0]["x"], tcs[0]["y"])
        elif self.layout.tc_pos is None:
            # Infer from building positions
            buildings = raw_state.get("_building_details", [])
            for b in buildings:
                if "TOWNCENTER" in b.get("name", "").upper().replace(" ", ""):
                    self.layout.tc_pos = Position(b["x"], b["y"])
                    break

        # If still no TC, infer base from villager positions
        if self.layout.tc_pos is None:
            units = raw_state.get("_all_units", [])
            vils = [u for u in units if u.get("class") == 904]
            if vils:
                xs = [u["x"] for u in vils]
                ys = [u["y"] for u in vils]
                self.layout.tc_pos = Position(sum(xs) / len(xs), sum(ys) / len(ys))

        # Map size
        if self.layout.map_width == 0:
            try:
                resp = self.ctrl.client.request({"action": "get_map"})
                self.layout.map_width = resp.get("width", 200)
                self.layout.map_height = resp.get("height", 200)
            except Exception:
                self.layout.map_width = 200
                self.layout.map_height = 200

        # Buildings
        self.layout.buildings = raw_state.get("_building_details", [])

        # Resources
        scan = raw_state.get("_resources_scan", {})
        if scan:
            for res_type in ("trees", "gold", "stone", "forage"):
                objects = scan.get(res_type, [])
                self.layout.resources[res_type] = ResourceCluster.from_objects(res_type, objects)

    def find_placement(
        self,
        building_name: str,
        goal: PlacementGoal = PlacementGoal.NEAR_TC,
        near: Position | None = None,
        avoid_radius: float = 3.0,
    ) -> Position | None:
        """
        Find the best position for a building based on the goal.

        Returns a Position or None if no valid spot found.
        """
        base = self.layout.base_center

        if goal == PlacementGoal.NEAR_TC:
            return self._place_near_tc(building_name, avoid_radius)

        elif goal == PlacementGoal.NEAR_RESOURCES:
            return self._place_near_resources(building_name, near)

        elif goal == PlacementGoal.WALL_EDGE:
            return self._place_wall_edge(building_name)

        elif goal == PlacementGoal.FARM_RING:
            center = near or base
            return self._place_farm_ring(center)

        elif goal == PlacementGoal.TIGHT_CLUSTER:
            return self._place_tight_cluster(building_name, near or base)

        elif goal == PlacementGoal.DEFENSIVE_PERIMETER:
            return self._place_defensive(building_name)

        return base.offset(5, 5)

    def find_mill_spot(self) -> Position | None:
        """Find optimal mill position — near berries, with farm space around it."""
        forage = self.layout.resources.get("forage")
        if forage and forage.count > 0:
            return forage.center.offset(-2, 0)
        # No berries — place near TC for farms
        if self.layout.tc_pos:
            return self.layout.tc_pos.offset(6, 0)
        return None

    def find_lumber_camp_spot(self) -> Position | None:
        """Find optimal lumber camp position — on the base-side edge of the treeline."""
        trees = self.layout.resources.get("trees")
        if not trees or trees.count == 0:
            return None
        base = self.layout.base_center
        # Place on the base-facing side of trees, far enough to be on walkable ground
        direction = base.direction_to(trees.center)
        # Try distances from tree center toward base until we find buildable ground
        for dist in range(3, 12):
            pos = trees.center.offset(-direction.x * dist, -direction.y * dist)
            if self._is_buildable(pos):
                return pos
        return None

    def find_mining_camp_spot(self, resource: str = "gold") -> Position | None:
        """Find spot for mining camp near gold or stone."""
        cluster = self.layout.resources.get(resource)
        if not cluster or cluster.count == 0:
            return None
        base = self.layout.base_center
        direction = base.direction_to(cluster.center)
        return cluster.center.offset(-direction.x * 2, -direction.y * 2)

    def find_farm_positions(self, center: Position, count: int = 4) -> list[Position]:
        """Find positions for farms in a ring around a center (TC or mill)."""
        offsets = [
            (3, 0), (-3, 0), (0, 3), (0, -3),
            (3, 3), (-3, 3), (3, -3), (-3, -3),
            (6, 0), (-6, 0), (0, 6), (0, -6),
        ]
        positions = []
        used = set()
        for b in self.layout.buildings:
            used.add((round(b.get("x", 0)), round(b.get("y", 0))))
        for dx, dy in offsets:
            pos = center.offset(dx, dy)
            key = (round(pos.x), round(pos.y))
            if key not in used:
                positions.append(pos)
                if len(positions) >= count:
                    break
        return positions

    def _is_buildable(self, pos: Position) -> bool:
        """Check if a tile is buildable by querying the game."""
        try:
            resp = self.ctrl.client.request({
                "action": "get_map_tiles",
                "x1": int(pos.x), "y1": int(pos.y),
                "x2": int(pos.x), "y2": int(pos.y),
            })
            tiles = resp.get("tiles", [])
            return tiles[0].get("buildable", False) if tiles else False
        except Exception:
            return True  # Assume buildable if can't check

    # ── Private placement methods ──

    def _place_near_tc(self, building_name: str, avoid_radius: float) -> Position | None:
        base = self.layout.base_center
        safe = self.layout.safe_side()

        existing_positions = set()
        for b in self.layout.buildings:
            existing_positions.add((round(b.get("x", 0)), round(b.get("y", 0))))
        for p in self.layout._placement_history:
            existing_positions.add((round(p.x), round(p.y)))

        # Spiral outward from TC on the safe side
        for dist in range(3, 20, 2):
            for angle_offset in [0, 0.5, -0.5, 1.0, -1.0, 1.5, -1.5]:
                angle = math.atan2(safe.y, safe.x) + angle_offset
                px = base.x + dist * math.cos(angle)
                py = base.y + dist * math.sin(angle)
                key = (round(px), round(py))
                if key not in existing_positions:
                    pos = Position(px, py)
                    self.layout._placement_history.append(pos)
                    return pos
        return base.offset(5, 5)

    def _place_near_resources(self, building_name: str, near: Position | None) -> Position | None:
        if near:
            return near.offset(-1, -1)
        return self.layout.base_center.offset(5, 5)

    def _place_wall_edge(self, building_name: str) -> Position | None:
        """Place buildings in a line on the defensive side — like a wall."""
        base = self.layout.base_center
        defense = self.layout.defensive_side()
        wall_center = base.offset(defense.x * 10, defense.y * 10)

        perp = Position(-defense.y, defense.x)

        existing = set()
        for b in self.layout.buildings:
            existing.add((round(b.get("x", 0)), round(b.get("y", 0))))

        for i in range(-5, 6):
            px = wall_center.x + perp.x * i * 3
            py = wall_center.y + perp.y * i * 3
            key = (round(px), round(py))
            if key not in existing:
                pos = Position(px, py)
                self.layout._placement_history.append(pos)
                return pos
        return wall_center

    def _place_farm_ring(self, center: Position) -> Position | None:
        positions = self.find_farm_positions(center, 1)
        return positions[0] if positions else center.offset(3, 0)

    def _place_tight_cluster(self, building_name: str, near: Position) -> Position | None:
        """Place buildings tightly packed near a position."""
        existing = set()
        for b in self.layout.buildings:
            existing.add((round(b.get("x", 0)), round(b.get("y", 0))))

        for dx in range(-6, 7, 2):
            for dy in range(-6, 7, 2):
                key = (round(near.x + dx), round(near.y + dy))
                if key not in existing:
                    pos = Position(near.x + dx, near.y + dy)
                    self.layout._placement_history.append(pos)
                    return pos
        return near.offset(2, 2)

    def _place_defensive(self, building_name: str) -> Position | None:
        return self._place_wall_edge(building_name)

    def get_nearest_resource(self, resource_type: str, to: Position | None = None) -> dict | None:
        """Get the nearest resource object of a type."""
        cluster = self.layout.resources.get(resource_type)
        if not cluster or not cluster.objects:
            return None
        origin = to or self.layout.base_center
        best = None
        best_dist = float("inf")
        for obj in cluster.objects:
            pos = Position(obj["x"], obj["y"])
            d = origin.distance_to(pos)
            if d < best_dist:
                best = obj
                best_dist = d
        return best
