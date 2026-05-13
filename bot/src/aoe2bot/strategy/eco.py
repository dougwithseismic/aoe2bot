"""Eco manager -- decides where idle villagers should go.

Drop-off-building aware: checks that a lumber camp / mining camp / mill
exists near the target resource cluster before assigning vils.  If not,
returns a DropoffNeeded instead of a VilAssignment so the caller can
build one first.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .world import WorldState

from .spatial import Position

logger = logging.getLogger(__name__)

MAX_DROPOFF_DISTANCE = 10.0

_SCAN_KEYS = {"food": "forage", "wood": "trees", "gold": "gold", "stone": "stone"}

_DROPOFF_BUILDINGS: dict[str, list[str]] = {
    "wood": ["LUMBER_CAMP", "TOWN_CENTER"],
    "food": ["MILL", "TOWN_CENTER"],
    "gold": ["MINING_CAMP", "TOWN_CENTER"],
    "stone": ["MINING_CAMP", "TOWN_CENTER"],
}

_DROPOFF_TO_BUILD: dict[str, str] = {
    "wood": "LUMBER_CAMP",
    "food": "MILL",
    "gold": "MINING_CAMP",
    "stone": "MINING_CAMP",
}


@dataclass
class VilAssignment:
    """A decision to send villagers to gather a specific resource."""
    resource: str
    vil_ids: list[int]
    target_id: int


@dataclass
class DropoffNeeded:
    """No drop-off building within range -- caller should build one first."""
    building_type: str
    near: Position
    resource: str


@dataclass
class _GatherCandidate:
    resource: str
    urgency: float
    target_id: int
    target_pos: Position


class EcoManager:
    """Calculates optimal villager distribution and assigns idle vils.

    Uses absolute vil counts (not ratios) based on age and current needs.
    Rotates assignments so we don't dump all vils on one depleted resource.
    """

    def __init__(self) -> None:
        self._last_assigned: str = ""

    # ── Distribution ──

    def get_desired_distribution_world(self, world: WorldState) -> dict[str, int]:
        """Target vil count per resource using WorldState."""
        n = world.villager_count
        age = world.age

        if age == 0:
            if n <= 6:
                return {"food": n, "wood": 0, "gold": 0, "stone": 0}
            if n <= 10:
                return {"food": 6, "wood": n - 6, "gold": 0, "stone": 0}
            wood = min(6, n - 10)
            return {"food": n - wood, "wood": wood, "gold": 0, "stone": 0}

        if age == 1:
            gold = 4 if world.gold < 100 else (3 if world.gold < 200 else 2)
            wood = max(4, min(6, n - 14))
            food = max(0, n - wood - gold)
            return {"food": food, "wood": wood, "gold": gold, "stone": 0}

        tc_count = world.building_count("TOWN_CENTER")
        stone = 3 if tc_count < 2 and world.stone < 100 else 0
        gold = 5
        wood = max(6, min(10, n - 20))
        food = max(0, n - wood - gold - stone)
        return {"food": food, "wood": wood, "gold": gold, "stone": stone}

    # ── Assignment ──

    def get_idle_assignment_world(
        self, world: WorldState, raw_state: dict | None = None,
    ) -> VilAssignment | DropoffNeeded | None:
        idle = world.idle_vils()
        if not idle:
            return None

        base = world.spatial.layout.base_center
        dist = self.get_desired_distribution_world(world)

        candidates: list[_GatherCandidate] = []
        dropoff_needed: DropoffNeeded | None = None
        best_dropoff_urgency: float = -1.0

        for res_name, desired in dist.items():
            if desired <= 0:
                continue

            urgency = self._score_urgency(res_name, desired, world)

            target = self._find_best_gather_target(world, raw_state, res_name, base)
            if target is None:
                continue

            target_id, target_pos = target

            nearest_dropoff = self._find_nearest_dropoff(world, res_name, target_pos)

            if nearest_dropoff is None:
                if urgency > best_dropoff_urgency:
                    best_dropoff_urgency = urgency
                    dropoff_needed = DropoffNeeded(
                        building_type=_DROPOFF_TO_BUILD[res_name],
                        near=target_pos,
                        resource=res_name,
                    )
                continue

            refined = self._find_best_gather_target(
                world, raw_state, res_name, nearest_dropoff,
            )
            if refined is not None:
                target_id, target_pos = refined

            candidates.append(_GatherCandidate(
                resource=res_name,
                urgency=urgency,
                target_id=target_id,
                target_pos=target_pos,
            ))

        if not candidates:
            if dropoff_needed is not None:
                return dropoff_needed

            wood_result = self._try_wood_fallback(world, raw_state, idle, base)
            if wood_result is not None:
                return wood_result
            return dropoff_needed

        candidates.sort(key=lambda c: c.urgency, reverse=True)
        chosen = candidates[0]
        self._last_assigned = chosen.resource

        sorted_idle = sorted(
            idle, key=lambda u: u.position.distance_to(chosen.target_pos),
        )
        count = min(6, len(sorted_idle))

        return VilAssignment(
            resource=chosen.resource,
            vil_ids=[u.id for u in sorted_idle[:count]],
            target_id=chosen.target_id,
        )

    # ── Private helpers ──

    def _score_urgency(
        self, res_name: str, desired: int, world: WorldState,
    ) -> float:
        urgency = float(desired)
        current = getattr(world, res_name, 0)
        if current < 100:
            urgency *= 2.0
        if current < 50:
            urgency *= 1.5
        if res_name == self._last_assigned:
            urgency *= 0.5
        return urgency

    @staticmethod
    def _find_best_gather_target(
        world: WorldState,
        raw_state: dict | None,
        resource: str,
        near: Position,
    ) -> tuple[int, Position] | None:
        """Find the resource object closest to *near*, checking MapKnowledge then raw scan."""
        map_key = _SCAN_KEYS.get(resource, resource)

        known = world.map.get_nearest_resource(map_key, near)
        if known is not None:
            return known.id, known.position

        if resource == "food":
            for alt in ("livestock",):
                known = world.map.get_nearest_resource(alt, near)
                if known is not None:
                    return known.id, known.position

        if raw_state is None:
            return None

        scan = raw_state.get("_resources_scan")
        if not scan:
            return None

        objects = scan.get(map_key, [])
        if resource == "food" and not objects:
            for fallback_key in ("livestock", "farms"):
                objects = scan.get(fallback_key, [])
                if objects:
                    break

        if not objects:
            return None

        best = min(objects, key=lambda o: near.distance_to(Position(o["x"], o["y"])))
        return best["id"], Position(best["x"], best["y"])

    @staticmethod
    def _find_nearest_dropoff(
        world: WorldState, resource: str, target_pos: Position,
    ) -> Position | None:
        """Return position of the closest completed drop-off building for *resource*,
        or None if nothing within MAX_DROPOFF_DISTANCE."""
        building_types = _DROPOFF_BUILDINGS.get(resource, [])

        best_pos: Position | None = None
        best_dist = MAX_DROPOFF_DISTANCE

        for btype in building_types:
            b = world.buildings.get_nearest(btype, target_pos)
            if b is None or not b.is_complete:
                continue
            d = target_pos.distance_to(b.position)
            if d < best_dist:
                best_dist = d
                best_pos = b.position

        return best_pos

    def _try_wood_fallback(
        self,
        world: WorldState,
        raw_state: dict | None,
        idle: list,
        base: Position,
    ) -> VilAssignment | DropoffNeeded | None:
        target = self._find_best_gather_target(world, raw_state, "wood", base)
        if target is None:
            return None

        target_id, target_pos = target

        nearest_dropoff = self._find_nearest_dropoff(world, "wood", target_pos)
        if nearest_dropoff is None:
            return DropoffNeeded(
                building_type="LUMBER_CAMP",
                near=target_pos,
                resource="wood",
            )

        refined = self._find_best_gather_target(
            world, raw_state, "wood", nearest_dropoff,
        )
        if refined is not None:
            target_id, target_pos = refined

        sorted_idle = sorted(
            idle, key=lambda u: u.position.distance_to(target_pos),
        )
        count = min(6, len(sorted_idle))
        return VilAssignment(
            resource="wood",
            vil_ids=[u.id for u in sorted_idle[:count]],
            target_id=target_id,
        )
