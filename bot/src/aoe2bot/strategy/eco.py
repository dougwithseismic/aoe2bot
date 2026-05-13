"""Eco manager -- decides where idle villagers should go.

No VillagerOccupation integration. No priority ratios.
Just: how many vils per resource, and where to send idle ones.

Supports both legacy AdaptiveState and new WorldState interfaces.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import AdaptiveState
    from .world import WorldState

logger = logging.getLogger(__name__)


@dataclass
class VilAssignment:
    """A decision to send villagers to gather a specific resource."""
    resource: str
    vil_ids: list[int]
    target_id: int


# Map from our resource names to scan_resources keys
_SCAN_KEYS = {"food": "forage", "wood": "trees", "gold": "gold", "stone": "stone"}
_FOOD_FALLBACKS = ("livestock", "farms")


class EcoManager:
    """Calculates optimal villager distribution and assigns idle vils.

    Uses absolute vil counts (not ratios) based on age and current needs.
    Rotates assignments so we don't dump all vils on one depleted resource.
    """

    def __init__(self) -> None:
        self._last_assigned: str = ""

    def get_desired_distribution(self, state: AdaptiveState) -> dict[str, int]:
        """Target vil count per resource given current game state."""
        n = state.villager_count

        if state.age == 0:
            # Dark Age: food-heavy, then wood for buildings
            if n <= 6:
                return {"food": n, "wood": 0, "gold": 0, "stone": 0}
            if n <= 10:
                return {"food": 6, "wood": n - 6, "gold": 0, "stone": 0}
            wood = min(6, n - 10)
            return {"food": n - wood, "wood": wood, "gold": 0, "stone": 0}

        if state.age == 1:
            # Feudal: need gold for Castle Age (800f + 200g)
            gold = 4 if state.gold < 100 else (3 if state.gold < 200 else 2)
            wood = max(4, min(6, n - 14))
            food = max(0, n - wood - gold)
            return {"food": food, "wood": wood, "gold": gold, "stone": 0}

        # Castle Age+: balanced with optional stone for extra TCs
        stone = 3 if state.tc_count < 2 and state.stone < 100 else 0
        gold = 5
        wood = max(6, min(10, n - 20))
        food = max(0, n - wood - gold - stone)
        return {"food": food, "wood": wood, "gold": gold, "stone": stone}

    def get_idle_assignment(self, state: AdaptiveState) -> VilAssignment | None:
        """Pick the best resource to send idle villagers to (legacy interface).

        Rotates between resources that need vils so we don't overload
        one depleted bush or treeline.
        """
        if not state.idle_vil_ids or not state.resources_scan:
            return None

        dist = self.get_desired_distribution(state)
        scan = state.resources_scan

        # Score each resource by urgency
        candidates: list[tuple[str, float, int]] = []
        for res_name, desired in dist.items():
            if desired <= 0:
                continue
            target_id = _find_resource_target(scan, res_name)
            if target_id is None:
                continue

            urgency = float(desired)
            # Boost urgency if we're low on this resource
            current = getattr(state, res_name, 0)
            if current < 100:
                urgency *= 2.0
            if current < 50:
                urgency *= 1.5
            # Penalize the resource we just assigned to (rotation)
            if res_name == self._last_assigned:
                urgency *= 0.5
            candidates.append((res_name, urgency, target_id))

        if not candidates:
            return None

        candidates.sort(key=lambda c: c[1], reverse=True)
        chosen_res, _, target_id = candidates[0]
        self._last_assigned = chosen_res

        # Send up to 4 vils per tick to avoid overloading one node
        count = min(4, len(state.idle_vil_ids))
        return VilAssignment(
            resource=chosen_res,
            vil_ids=state.idle_vil_ids[:count],
            target_id=target_id,
        )

    # ── WorldState-aware interface ──

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

        # Castle Age+
        tc_count = world.building_count("TOWN_CENTER")
        stone = 3 if tc_count < 2 and world.stone < 100 else 0
        gold = 5
        wood = max(6, min(10, n - 20))
        food = max(0, n - wood - gold - stone)
        return {"food": food, "wood": wood, "gold": gold, "stone": stone}

    def get_idle_assignment_world(
        self, world: WorldState, raw_state: dict | None = None,
    ) -> VilAssignment | None:
        """Pick the best resource to send idle villagers to using WorldState.

        Uses world.map.get_nearest_resource() to find gathering targets
        instead of raw scan data. Falls back to scan data if map has no
        resources discovered yet.
        """
        idle = world.idle_vils()
        if not idle:
            return None

        idle_ids = [u.id for u in idle]
        base = world.spatial.layout.base_center
        dist = self.get_desired_distribution_world(world)

        # Score each resource by urgency, find target via MapKnowledge
        candidates: list[tuple[str, float, int]] = []
        for res_name, desired in dist.items():
            if desired <= 0:
                continue

            target_id = self._find_target_via_map(world, res_name, base)

            # Fall back to raw scan if MapKnowledge doesn't have the resource
            if target_id is None and raw_state is not None:
                scan = raw_state.get("_resources_scan")
                if scan:
                    target_id = _find_resource_target(scan, res_name)

            if target_id is None:
                continue

            urgency = float(desired)
            current = getattr(world, res_name, 0)
            if current < 100:
                urgency *= 2.0
            if current < 50:
                urgency *= 1.5
            if res_name == self._last_assigned:
                urgency *= 0.5
            candidates.append((res_name, urgency, target_id))

        if not candidates:
            # Fallback: send idle vils to wood (trees always exist)
            wood_target = self._find_target_via_map(world, "wood", base)
            if wood_target is None and raw_state is not None:
                scan = raw_state.get("_resources_scan")
                if scan:
                    wood_target = _find_resource_target(scan, "wood")
            if wood_target is not None:
                count = min(6, len(idle_ids))
                return VilAssignment(
                    resource="wood",
                    vil_ids=idle_ids[:count],
                    target_id=wood_target,
                )
            return None

        candidates.sort(key=lambda c: c[1], reverse=True)
        chosen_res, _, target_id = candidates[0]
        self._last_assigned = chosen_res

        count = min(6, len(idle_ids))
        return VilAssignment(
            resource=chosen_res,
            vil_ids=idle_ids[:count],
            target_id=target_id,
        )

    @staticmethod
    def _find_target_via_map(
        world: WorldState, resource: str, near: object,
    ) -> int | None:
        """Find a resource target ID using MapKnowledge nearest-resource lookup."""
        from .spatial import Position

        if not isinstance(near, Position):
            return None

        # Map resource name to MapKnowledge resource_type
        map_keys = {"food": "forage", "wood": "trees", "gold": "gold", "stone": "stone"}
        map_key = map_keys.get(resource)
        if map_key is None:
            return None

        known = world.map.get_nearest_resource(map_key, near)
        if known is not None:
            return known.id

        # Food fallback: try forage first (already tried), then look for farms
        # Farms don't appear in MapKnowledge resources, so we'd need raw scan
        return None


def _find_resource_target(scan: dict, resource: str) -> int | None:
    """Find the first valid resource object ID from a scan_resources response."""
    scan_key = _SCAN_KEYS.get(resource, resource)
    objects = scan.get(scan_key, [])
    if objects:
        return objects[0].get("id")
    # Food fallback: try livestock, then farms
    if resource == "food":
        for key in _FOOD_FALLBACKS:
            objects = scan.get(key, [])
            if objects:
                return objects[0].get("id")
    return None
