"""Building lifecycle tracker — construction progress, completions, type queries."""

from __future__ import annotations

from dataclasses import dataclass, field

from .spatial import Position
from .state import _normalize

_CANONICAL_TYPES: list[tuple[str, str]] = [
    ("TOWNCENTER", "TOWN_CENTER"),
    ("LUMBERCAMP", "LUMBER_CAMP"),
    ("MININGCAMP", "MINING_CAMP"),
    ("ARCHERYRANGE", "ARCHERY_RANGE"),
    ("HOUSE", "HOUSE"),
    ("FARM", "FARM"),
    ("BARRACKS", "BARRACKS"),
    ("BLACKSMITH", "BLACKSMITH"),
    ("MARKET", "MARKET"),
    ("STABLE", "STABLE"),
    ("CASTLE", "CASTLE"),
]

# MILL must not match WINDMILL/LUMBER_MILL, so it gets special handling
_MILL_FALSE_POSITIVES = ("WINDMILL", "LUMBERMILL")


def _canonicalize(normalized: str) -> str:
    for fragment, canonical in _CANONICAL_TYPES:
        if fragment in normalized:
            return canonical
    if "MILL" in normalized and not any(fp in normalized for fp in _MILL_FALSE_POSITIVES):
        return "MILL"
    return normalized


@dataclass
class TrackedBuilding:
    id: int
    name: str
    normalized_name: str
    building_type: str
    position: Position
    hp: int
    max_hp: int
    is_complete: bool
    construction_pct: float
    first_seen: float
    completed_at: float | None = None
    builders: list[int] = field(default_factory=list)


class BuildingTracker:
    def __init__(self) -> None:
        self._buildings: dict[int, TrackedBuilding] = {}
        self._previous_ids: set[int] = set()
        self._previous_incomplete: set[int] = set()
        self._new_buildings: list[TrackedBuilding] = []
        self._completed_buildings: list[TrackedBuilding] = []

    def update(self, buildings: list[dict], game_time: float) -> None:
        current_ids: set[int] = set()
        current_incomplete: set[int] = set()
        self._new_buildings = []
        self._completed_buildings = []

        for raw in buildings:
            bid = raw.get("id") or hash((raw.get("name", ""), round(raw.get("x", 0)), round(raw.get("y", 0))))
            current_ids.add(bid)

            hp = raw.get("hp", 0)
            max_hp = raw.get("maxHp", 1)
            complete = hp >= max_hp
            name = raw.get("name", "")
            normalized = _normalize(name)

            if not complete:
                current_incomplete.add(bid)

            existing = self._buildings.get(bid)
            if existing is None:
                tb = TrackedBuilding(
                    id=bid,
                    name=name,
                    normalized_name=normalized,
                    building_type=_canonicalize(normalized),
                    position=Position(raw.get("x", 0.0), raw.get("y", 0.0)),
                    hp=hp,
                    max_hp=max_hp,
                    is_complete=complete,
                    construction_pct=(hp / max_hp * 100) if max_hp > 0 else 0.0,
                    first_seen=game_time,
                    completed_at=game_time if complete else None,
                )
                self._buildings[bid] = tb
                if bid not in self._previous_ids:
                    self._new_buildings.append(tb)
                if complete and bid in self._previous_incomplete:
                    self._completed_buildings.append(tb)
            else:
                existing.hp = hp
                existing.max_hp = max_hp
                existing.construction_pct = (hp / max_hp * 100) if max_hp > 0 else 0.0
                existing.position = Position(raw.get("x", 0.0), raw.get("y", 0.0))

                was_incomplete = not existing.is_complete
                existing.is_complete = complete

                if complete and was_incomplete:
                    existing.completed_at = game_time
                    self._completed_buildings.append(existing)

        self._previous_ids = current_ids
        self._previous_incomplete = current_incomplete

    def get_by_type(self, building_type: str) -> list[TrackedBuilding]:
        needle = _normalize(building_type)
        return [
            b for b in self._buildings.values()
            if needle in b.normalized_name or needle == _normalize(b.building_type)
        ]

    def count_type(self, building_type: str) -> int:
        return len(self.get_by_type(building_type))

    def has_complete(self, building_type: str) -> bool:
        return any(b.is_complete for b in self.get_by_type(building_type))

    def get_in_progress(self) -> list[TrackedBuilding]:
        return [b for b in self._buildings.values() if not b.is_complete]

    def get_nearest(self, building_type: str, pos: Position) -> TrackedBuilding | None:
        matches = self.get_by_type(building_type)
        if not matches:
            return None
        return min(matches, key=lambda b: pos.distance_to(b.position))

    def was_building_placed(
        self, building_type: str, near: Position, since: float
    ) -> bool:
        needle = _normalize(building_type)
        for b in self._buildings.values():
            if needle not in b.normalized_name and needle != _normalize(b.building_type):
                continue
            if b.first_seen >= since and near.distance_to(b.position) <= 5.0:
                return True
        return False

    def get_new_buildings(self) -> list[TrackedBuilding]:
        return list(self._new_buildings)

    def get_completed_buildings(self) -> list[TrackedBuilding]:
        return list(self._completed_buildings)
