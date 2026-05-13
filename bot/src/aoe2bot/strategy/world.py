"""WorldState orchestrator — single source of truth for all game state."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .buildings import BuildingTracker
from .commands import CommandTracker
from .event_queue import EventQueue
from .map_knowledge import MapKnowledge
from .spatial import Position, SpatialEngine
from .units import TrackedUnit, UnitTask, UnitTracker

if TYPE_CHECKING:
    from ..controller import GameController

logger = logging.getLogger(__name__)


class WorldState:

    def __init__(self, ctrl: GameController) -> None:
        self.units = UnitTracker()
        self.buildings = BuildingTracker()
        self.commands = CommandTracker()
        self.map = MapKnowledge()
        self.queue = EventQueue()
        self.spatial = SpatialEngine(ctrl)

        self.game_time: float = 0.0
        self.age: int = 0
        self.food: float = 0.0
        self.wood: float = 0.0
        self.gold: float = 0.0
        self.stone: float = 0.0
        self.population: int = 0
        self.housing_headroom: int = 0
        self.pop_headroom: int = 0
        self.villager_count: int = 0
        self.available: dict[str, dict] = {}

    def update(self, raw_state: dict) -> None:
        self._update_core(raw_state)
        self.units.update(raw_state.get("_all_units", []), self.game_time)
        self.buildings.update(raw_state.get("_building_details", []), self.game_time)
        self.commands.update(
            self.units, self.buildings, self.game_time, population=self.population
        )
        unit_positions = [u.position for u in self.units.get_all()]
        self.map.update(raw_state.get("_resources_scan"), unit_positions, self.game_time)
        self.spatial.refresh(raw_state)

    # ── Convenience queries ──

    def idle_vils(self) -> list[TrackedUnit]:
        return self.units.get_idle_vils()

    def vils_gathering(self, resource: str) -> list[TrackedUnit]:
        return self.units.get_vils_by_task(UnitTask.GATHERING)

    def can_afford(
        self, food: float = 0, wood: float = 0, gold: float = 0, stone: float = 0
    ) -> bool:
        return (
            self.food >= food
            and self.wood >= wood
            and self.gold >= gold
            and self.stone >= stone
        )

    def tc_is_training(self) -> bool:
        return self.commands.has_active_train()

    def tc_is_complete(self) -> bool:
        return self.buildings.has_complete("TOWN_CENTER")

    def has_building(self, building_type: str, complete_only: bool = True) -> bool:
        matches = self.buildings.get_by_type(building_type)
        if complete_only:
            return any(b.is_complete for b in matches)
        return len(matches) > 0

    def building_count(self, building_type: str) -> int:
        return self.buildings.count_type(building_type)

    def exploration_around_base(self) -> float:
        base = self.spatial.layout.base_center
        return self.map.get_exploration_pct(base, 20)

    def nearest_idle_vils(self, pos: Position, count: int = 6) -> list[TrackedUnit]:
        """Get the N closest idle villagers to a position."""
        idle = self.units.get_idle_vils()
        idle.sort(key=lambda u: u.position.distance_to(pos))
        return idle[:count]

    def nearest_resource_from_scan(
        self, raw_state: dict, resource_type: str, near: Position | None = None,
    ) -> dict | None:
        """Find the closest resource object from scan data.

        resource_type: "trees", "forage", "gold", "stone"
        Returns dict with id, x, y or None.
        """
        origin = near or self.spatial.layout.base_center
        scan = raw_state.get("_resources_scan", {})
        objects = scan.get(resource_type, [])
        if not objects:
            return None
        return min(objects, key=lambda o: origin.distance_to(Position(o["x"], o["y"])))

    # ── Private ──

    def _update_core(self, raw: dict) -> None:
        self.game_time = raw.get("time", 0.0)
        self.age = raw.get("age", 0)

        res = raw.get("resources", {})
        self.food = res.get("food", 0.0)
        self.wood = res.get("wood", 0.0)
        self.gold = res.get("gold", 0.0)
        self.stone = res.get("stone", 0.0)

        pop = raw.get("population", {})
        self.population = pop.get("current", 0)
        self.housing_headroom = pop.get("housing_headroom", 0)
        self.pop_headroom = pop.get("headroom", 0)

        self.villager_count = raw.get("villagerCount", 0)

        avail_raw = raw.get("_available", {})
        if avail_raw:
            self.available = avail_raw
