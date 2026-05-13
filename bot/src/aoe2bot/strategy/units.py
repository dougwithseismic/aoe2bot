"""Unit tracking — observe every owned unit's position, state, and inferred task."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto

from .spatial import Position

logger = logging.getLogger(__name__)

VILLAGER_CLASS = 904
SCOUT_CLASS = 961

MOVEMENT_THRESHOLD = 0.3


class UnitTask(Enum):
    IDLE = auto()
    WALKING = auto()
    GATHERING = auto()
    BUILDING = auto()
    SCOUTING = auto()


@dataclass
class TrackedUnit:
    id: int
    unit_class: int
    position: Position
    previous_position: Position | None = None
    hp: int = 0
    max_hp: int = 0
    is_idle: bool = True
    is_moving: bool = False
    inferred_task: UnitTask = UnitTask.IDLE
    task_target: int | None = None
    last_command: str | None = None
    last_command_time: float = 0.0
    last_seen: float = 0.0

    @property
    def is_villager(self) -> bool:
        return self.unit_class == VILLAGER_CLASS

    @property
    def is_scout(self) -> bool:
        return self.unit_class == SCOUT_CLASS

    @property
    def hp_pct(self) -> float:
        return (self.hp / self.max_hp * 100) if self.max_hp > 0 else 0.0


class UnitTracker:

    def __init__(self) -> None:
        self._units: dict[int, TrackedUnit] = {}
        self._new_units: list[TrackedUnit] = []
        self._lost_units: list[TrackedUnit] = []

    def get_new_units(self) -> list[TrackedUnit]:
        return list(self._new_units)

    def get_lost_units(self) -> list[TrackedUnit]:
        return list(self._lost_units)

    def update(self, all_units: list[dict], game_time: float) -> None:
        seen_ids: set[int] = set()
        self._new_units = []
        self._lost_units = []

        for raw in all_units:
            uid = raw.get("id")
            if uid is None:
                continue
            seen_ids.add(uid)

            pos = Position(raw.get("x", 0.0), raw.get("y", 0.0))
            raw_idle = bool(raw.get("idle", False))
            raw_moving = bool(raw.get("moving", False))

            existing = self._units.get(uid)
            if existing is not None:
                previous_pos = existing.position
                moved = previous_pos.distance_to(pos) > MOVEMENT_THRESHOLD
                existing.previous_position = previous_pos
                existing.position = pos
                existing.hp = raw.get("hp", existing.hp)
                existing.max_hp = raw.get("maxHp", existing.max_hp)
                existing.is_idle = raw_idle
                existing.is_moving = moved or raw_moving
                existing.last_seen = game_time
                existing.inferred_task = self._infer_task(existing)
            else:
                unit = TrackedUnit(
                    id=uid,
                    unit_class=raw.get("class", 0),
                    position=pos,
                    hp=raw.get("hp", 0),
                    max_hp=raw.get("maxHp", 0),
                    is_idle=raw_idle,
                    is_moving=raw_moving,
                    last_seen=game_time,
                )
                unit.inferred_task = self._infer_task(unit)
                self._units[uid] = unit
                self._new_units.append(unit)

        # Remove units no longer reported by the game
        stale = self._units.keys() - seen_ids
        for uid in stale:
            self._lost_units.append(self._units[uid])
            del self._units[uid]

    def get_unit(self, unit_id: int) -> TrackedUnit | None:
        return self._units.get(unit_id)

    def get_all(self) -> list[TrackedUnit]:
        return list(self._units.values())

    def get_idle_vils(self) -> list[TrackedUnit]:
        return [
            u for u in self._units.values()
            if u.unit_class == VILLAGER_CLASS and u.is_idle
        ]

    def get_vils_by_task(self, task: UnitTask) -> list[TrackedUnit]:
        return [
            u for u in self._units.values()
            if u.unit_class == VILLAGER_CLASS and u.inferred_task == task
        ]

    def get_nearest_vil(self, pos: Position, prefer_idle: bool = True) -> TrackedUnit | None:
        vils = [u for u in self._units.values() if u.unit_class == VILLAGER_CLASS]
        if not vils:
            return None

        if prefer_idle:
            idle = [v for v in vils if v.is_idle]
            if idle:
                return min(idle, key=lambda v: v.position.distance_to(pos))

        return min(vils, key=lambda v: v.position.distance_to(pos))

    def get_vils_near(self, pos: Position, radius: float) -> list[TrackedUnit]:
        return [
            u for u in self._units.values()
            if u.unit_class == VILLAGER_CLASS
            and u.position.distance_to(pos) <= radius
        ]

    def count_vils_on_resource(self, resource_type: str) -> int:
        """Count villagers inferred to be gathering.

        resource_type is accepted for future use when we can distinguish
        food/wood/gold/stone gatherers.  For now returns all GATHERING vils.
        """
        return len(self.get_vils_by_task(UnitTask.GATHERING))

    def record_command(self, unit_id: int, command: str, game_time: float) -> None:
        unit = self._units.get(unit_id)
        if unit is None:
            return
        unit.last_command = command
        unit.last_command_time = game_time

    def was_command_acknowledged(self, unit_id: int) -> bool:
        """True if the unit started moving after we issued its last command."""
        unit = self._units.get(unit_id)
        if unit is None:
            return False
        if unit.last_command is None:
            return False
        return unit.is_moving and unit.last_seen > unit.last_command_time

    # ── Private ──

    def _infer_task(self, unit: TrackedUnit) -> UnitTask:
        if unit.is_idle:
            return UnitTask.IDLE

        if unit.is_moving:
            # If we issued a scout/move command and they're still moving, call it SCOUTING
            if unit.last_command in ("scout", "move") and unit.last_command_time > 0:
                return UnitTask.SCOUTING
            return UnitTask.WALKING

        # Not idle and not moving — stationary doing work.
        # Without BuildingTracker integration we can't distinguish GATHERING
        # from BUILDING, so default to GATHERING.
        return UnitTask.GATHERING
