"""Fast Castle strategy — direct execution, no priority queue.

Every tick: check everything, do everything that needs doing.
Multiple commands per tick via IPC. No EventQueue.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..protocol import Technology
from .base import BaseStrategy
from .eco import DropoffNeeded, EcoManager, VilAssignment
from .spatial import PlacementGoal, Position

if TYPE_CHECKING:
    from ..controller import GameController
    from .world import WorldState

logger = logging.getLogger(__name__)

_AGE_NAMES = {0: "Dark", 1: "Feudal", 2: "Castle", 3: "Imperial"}
_TECH_STATE_KEY = "_tech_state"


class FastCastleStrategy(BaseStrategy):

    TARGET_VIL_POP = 40

    def __init__(self, ctrl: GameController):
        super().__init__(ctrl)
        self.eco = EcoManager()
        self._tick_count = 0
        self._scouting_enabled = False
        self._mill_built = False
        self._lc_built = False
        self._last_pop = 0
        self._vils_assigned_food = 0
        self._vils_assigned_wood = 0
        self._gather_point_set = False

    @property
    def name(self) -> str:
        return "fast-castle"

    def on_start(self) -> None:
        self.running = True
        logger.info("FastCastle strategy started (direct execution)")

    def on_tick(self, raw_state: dict, world: WorldState | None = None) -> str | None:
        if world is None:
            return None

        self._tick_count += 1
        w = world
        actions: list[str] = []

        # ── Scouting — always, even during TC build ──
        self._do_scout(w)

        # ── TC (Nomad) ──
        if not self._has_tc(w, raw_state):
            self._do_build_tc(w, actions)
            self._log(w, actions)
            return actions[0] if actions else None

        # ── Train villager ──
        self._do_train_vil(w, actions)

        # ── TC gather point — alternate between food and wood ──
        self._do_gather_point(w, raw_state, actions)

        # ── Houses ──
        self._do_houses(w, actions)

        # ── Mill ──
        self._do_mill(w, actions)

        # ── Lumber camp ──
        self._do_lumber_camp(w, actions)

        # ── Idle vils → assign to work ──
        self._do_assign_idle(w, raw_state, actions)

        # ── Farms ──
        self._do_farms(w, actions)

        # ── Livestock ──
        self._do_livestock(w, raw_state, actions)

        # ── Age-specific ──
        if w.age == 0:
            self._do_dark_age(w, raw_state, actions)
        elif w.age == 1:
            self._do_feudal(w, raw_state, actions)
        elif w.age >= 2:
            self._do_castle(w, raw_state, actions)

        self._log(w, actions)
        return ", ".join(actions) if actions else None

    def is_complete(self, raw_state: dict) -> bool:
        age = raw_state.get("age", 0)
        vil = raw_state.get("villagerCount", 0)
        pop = raw_state.get("population", {}).get("current", 0)
        return age >= 2 and vil >= 35 and pop >= 50

    # ================================================================
    # Helpers
    # ================================================================

    def _has_tc(self, w: WorldState, raw_state: dict) -> bool:
        if w.has_building("TOWN_CENTER", complete_only=False):
            return True
        if raw_state.get("_tcs"):
            return True
        return False

    def _place(self, building: str, x: float, y: float) -> dict:
        resp = self.ctrl.place_building(building, x, y)
        if resp.get("action") == "error":
            logger.warning("Build %s failed: %s", building, resp.get("error"))
        return resp

    def _smart_build(self, building: str) -> dict:
        resp = self.ctrl.smart_build(building, padding=0)
        if resp.get("action") == "error":
            logger.warning("Smart build %s failed: %s", building, resp.get("error"))
        return resp

    def _research(self, name: str, fn) -> dict:
        resp = fn()
        if resp.get("action") == "error":
            logger.warning("Research %s failed: %s", name, resp.get("error"))
        return resp

    # ================================================================
    # TC
    # ================================================================

    def _do_build_tc(self, w: WorldState, actions: list[str]) -> None:
        if not w.can_afford(wood=275, stone=100):
            return
        pos = w.spatial.layout.base_center
        logger.info("Placing TC at %.0f, %.0f", pos.x, pos.y)
        resp = self._place("TOWN_CENTER", pos.x, pos.y)
        if resp.get("action") != "error":
            actions.append("build_tc")

    # ================================================================
    # Scout — direct call, not queued
    # ================================================================

    def _do_scout(self, w: WorldState) -> None:
        if self._scouting_enabled:
            return
        scout_id = None
        for u in w.units.get_all():
            if u.is_scout:
                scout_id = u.id
                break
        msg: dict = {"action": "scout"}
        if scout_id:
            msg["unit_id"] = scout_id
        try:
            resp = self.ctrl.client.request(msg)
            if resp.get("success"):
                self._scouting_enabled = True
                logger.info("Auto-scout enabled (unit=%s)", scout_id)
        except Exception:
            pass

    # ================================================================
    # Train villager
    # ================================================================

    def _do_train_vil(self, w: WorldState, actions: list[str]) -> None:
        if not w.tc_is_complete():
            return
        if w.villager_count >= self.TARGET_VIL_POP:
            return
        if w.housing_headroom <= 0:
            return
        if not w.can_afford(food=50):
            return
        resp = self.ctrl.train_villager()
        if resp.get("action") != "error":
            actions.append("train_vil")

    # ================================================================
    # TC Gather Point — new vils auto-walk to the right resource
    # ================================================================

    def _do_gather_point(self, w: WorldState, raw_state: dict, actions: list[str]) -> None:
        if not w.tc_is_complete():
            return

        tc = w.spatial.layout.tc_pos
        if tc is None:
            return

        dist = self.eco.get_desired_distribution_world(w)

        # Decide: should next vil go to food or wood?
        food_need = dist.get("food", 0)
        wood_need = dist.get("wood", 0)

        if wood_need > 0 and (self._vils_assigned_wood < wood_need or w.wood < 100):
            target = w.nearest_resource_from_scan(raw_state, "trees", near=tc)
            resource = "wood"
        else:
            target = w.nearest_resource_from_scan(raw_state, "forage", near=tc)
            resource = "food"

        if target is None:
            return

        # Set gather point every 10 ticks (don't spam)
        if self._tick_count % 10 == 1:
            try:
                self.ctrl.client.request({
                    "action": "set_gather_point",
                    "x": target["x"], "y": target["y"],
                })
            except Exception:
                pass

        # Track new vils — when pop increases, count where they're going
        if w.population > self._last_pop and self._last_pop > 0:
            new_vils = w.population - self._last_pop
            if resource == "food":
                self._vils_assigned_food += new_vils
            else:
                self._vils_assigned_wood += new_vils
        self._last_pop = w.population

    # ================================================================
    # Houses
    # ================================================================

    def _do_houses(self, w: WorldState, actions: list[str]) -> None:
        if w.housing_headroom > 3:
            return
        if not w.can_afford(wood=25):
            return
        resp = self._smart_build("HOUSE")
        if resp.get("action") != "error":
            actions.append("house")

    # ================================================================
    # Mill
    # ================================================================

    def _do_mill(self, w: WorldState, actions: list[str]) -> None:
        if self._mill_built or w.has_building("MILL", complete_only=False):
            self._mill_built = True
            return
        if not w.can_afford(wood=100):
            return
        resp = self._smart_build("MILL")
        if resp.get("action") != "error":
            self._mill_built = True
            actions.append("mill")

    # ================================================================
    # Lumber camp
    # ================================================================

    def _do_lumber_camp(self, w: WorldState, actions: list[str]) -> None:
        if self._lc_built or w.has_building("LUMBER_CAMP", complete_only=False):
            self._lc_built = True
            return
        if not w.can_afford(wood=100):
            return
        resp = self._smart_build("LUMBER_CAMP")
        if resp.get("action") != "error":
            self._lc_built = True
            actions.append("lumber_camp")

    # ================================================================
    # Assign idle vils
    # ================================================================

    def _do_assign_idle(self, w: WorldState, raw_state: dict, actions: list[str]) -> None:
        idle = w.idle_vils()
        if not idle:
            return

        tc = w.spatial.layout.tc_pos or w.spatial.layout.base_center
        dist = self.eco.get_desired_distribution_world(w)

        # Assign idle vils based on desired distribution
        # Pick the resource with the biggest deficit
        resource_order: list[tuple[str, str]] = []
        if dist.get("food", 0) > 0:
            resource_order.append(("food", "forage"))
        if dist.get("wood", 0) > 0:
            resource_order.append(("wood", "trees"))
        if dist.get("gold", 0) > 0:
            resource_order.append(("gold", "gold"))
        if dist.get("stone", 0) > 0:
            resource_order.append(("stone", "stone"))

        # Sort by urgency: low stockpile = assign first
        def urgency(res_scan: tuple[str, str]) -> float:
            res = res_scan[0]
            current = getattr(w, res, 0)
            desired = dist.get(res, 0)
            return desired * (2.0 if current < 100 else 1.0)

        resource_order.sort(key=urgency, reverse=True)

        remaining = list(idle)
        for res, scan_key in resource_order:
            if not remaining:
                break
            target = w.nearest_resource_from_scan(raw_state, scan_key, near=tc)
            if not target:
                continue

            target_pos = Position(target["x"], target["y"])
            count = min(dist.get(res, 3), len(remaining))
            if count <= 0:
                continue

            # Pick closest idle vils to this resource
            remaining.sort(key=lambda u: u.position.distance_to(target_pos))
            batch = remaining[:count]
            remaining = remaining[count:]

            self.ctrl.attack_target([u.id for u in batch], target["id"])
            actions.append(f"assign_{len(batch)}_{res}")

    # ================================================================
    # Farms
    # ================================================================

    def _do_farms(self, w: WorldState, actions: list[str]) -> None:
        if not w.has_building("MILL", complete_only=False):
            return
        if w.food > 200:
            return
        if not w.can_afford(wood=60):
            return

        center = w.spatial.layout.tc_pos or w.spatial.layout.base_center
        pos = w.spatial.find_placement("FARM", goal=PlacementGoal.FARM_RING, near=center)
        if pos is None:
            pos = center.offset(3, 3)

        resp = self._place("FARM", pos.x, pos.y)
        if resp.get("action") != "error":
            actions.append("farm")

    # ================================================================
    # Livestock
    # ================================================================

    def _do_livestock(self, w: WorldState, raw_state: dict, actions: list[str]) -> None:
        if not w.tc_is_complete():
            return
        livestock = raw_state.get("_livestock", {})
        owned = livestock.get("owned", [])
        if not owned:
            return
        tc_pos = w.spatial.layout.tc_pos
        if tc_pos is None:
            return
        far = [o for o in owned if Position(o["x"], o["y"]).distance_to(tc_pos) > 5.0]
        if not far:
            return
        ids = [o["id"] for o in far[:4]]
        self.ctrl.move_units(ids, tc_pos.x, tc_pos.y)
        actions.append("herd")

    # ================================================================
    # Dark Age specifics
    # ================================================================

    def _do_dark_age(self, w: WorldState, raw_state: dict, actions: list[str]) -> None:
        tech = raw_state.get(_TECH_STATE_KEY, {})

        # Loom at 12+ vils
        loom = tech.get(str(Technology.LOOM), {})
        if (
            not loom.get("researched")
            and w.villager_count >= 12
            and w.can_afford(food=50)
        ):
            resp = self._research("loom", self.ctrl.research_loom)
            if resp.get("action") != "error":
                actions.append("loom")

        # Feudal advance
        if w.can_afford(food=500):
            resp = self._research("feudal", self.ctrl.advance_to_feudal)
            if resp.get("action") != "error":
                actions.append("advance_feudal")

    # ================================================================
    # Feudal Age
    # ================================================================

    def _do_feudal(self, w: WorldState, raw_state: dict, actions: list[str]) -> None:
        # Blacksmith
        if not w.has_building("BLACKSMITH", complete_only=False) and w.can_afford(wood=150):
            resp = self._smart_build("BLACKSMITH")
            if resp.get("action") != "error":
                actions.append("blacksmith")

        # Market
        if not w.has_building("MARKET", complete_only=False) and w.can_afford(wood=175):
            resp = self._smart_build("MARKET")
            if resp.get("action") != "error":
                actions.append("market")

        # Eco techs
        tech = raw_state.get(_TECH_STATE_KEY, {})
        if not tech.get(str(Technology.DOUBLE_BIT_AXE), {}).get("researched") and w.has_building("LUMBER_CAMP"):
            self._research("dba", lambda: self.ctrl.research(Technology.DOUBLE_BIT_AXE))

        if not tech.get(str(Technology.HORSE_COLLAR), {}).get("researched") and w.has_building("MILL"):
            self._research("hc", lambda: self.ctrl.research(Technology.HORSE_COLLAR))

        # Castle advance
        if (
            w.can_afford(food=800, gold=200)
            and w.has_building("BLACKSMITH")
            and w.has_building("MARKET")
        ):
            resp = self._research("castle", self.ctrl.advance_to_castle)
            if resp.get("action") != "error":
                actions.append("advance_castle")

    # ================================================================
    # Castle Age
    # ================================================================

    def _do_castle(self, w: WorldState, raw_state: dict, actions: list[str]) -> None:
        # 2nd TC
        if w.building_count("TOWN_CENTER") < 2 and w.can_afford(wood=275, stone=100):
            pos = w.spatial.find_placement("TOWN_CENTER", goal=PlacementGoal.NEAR_TC)
            if pos:
                resp = self._place("TOWN_CENTER", pos.x, pos.y)
                if resp.get("action") != "error":
                    actions.append("2nd_tc")

        # 3rd TC
        if (
            w.building_count("TOWN_CENTER") == 2
            and w.villager_count >= 25
            and w.can_afford(wood=275, stone=100)
        ):
            pos = w.spatial.find_placement("TOWN_CENTER", goal=PlacementGoal.NEAR_TC)
            if pos:
                resp = self._place("TOWN_CENTER", pos.x, pos.y)
                if resp.get("action") != "error":
                    actions.append("3rd_tc")

        # Barracks
        if not w.has_building("BARRACKS", complete_only=False) and w.can_afford(wood=175):
            resp = self._smart_build("BARRACKS")
            if resp.get("action") != "error":
                actions.append("barracks")

        # Stable
        if (
            not w.has_building("STABLE", complete_only=False)
            and w.has_building("BARRACKS")
            and w.can_afford(wood=175)
        ):
            resp = self._smart_build("STABLE")
            if resp.get("action") != "error":
                actions.append("stable")

        # Knights
        if (
            w.has_building("STABLE")
            and w.villager_count >= 25
            and w.can_afford(food=120, gold=75)
        ):
            resp = self.ctrl.train_knight()
            if resp.get("action") != "error":
                actions.append("knight")

        # Eco techs
        tech = raw_state.get(_TECH_STATE_KEY, {})
        if not tech.get(str(Technology.WHEELBARROW), {}).get("researched"):
            self._research("wb", lambda: self.ctrl.research(Technology.WHEELBARROW))
        if not tech.get(str(Technology.BOW_SAW), {}).get("researched") and w.has_building("LUMBER_CAMP"):
            self._research("bs", lambda: self.ctrl.research(Technology.BOW_SAW))

    # ================================================================
    # Logging
    # ================================================================

    def _log(self, w: WorldState, actions: list[str]) -> None:
        m, s = divmod(int(w.game_time), 60)
        age = _AGE_NAMES.get(w.age, "?")
        idle = len(w.idle_vils())
        cap = w.population + w.housing_headroom
        act = ", ".join(actions) if actions else "-"

        if actions or self._tick_count % 10 == 0:
            logger.info(
                "[%d:%02d] %s | Pop %d/%d | F:%.0f W:%.0f G:%.0f S:%.0f | Idle:%d | %s",
                m, s, age, w.population, cap,
                w.food, w.wood, w.gold, w.stone,
                idle, act,
            )
