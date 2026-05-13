"""Fast Castle 27+2 Boom — proper build order.

Based on the standard AoE2 Fast Castle build:
  Vils 1-6:   sheep (food under TC)
  Vil 7:      build lumber camp → wood
  Vils 8-10:  wood
  Vil 11:     lure boar (we skip boar — send to sheep/berries)
  Vil 12:     build mill near berries → berries
  Vils 13-16: berries
  Vils 17-18: build farms
  Vil 19:     build 2nd lumber camp → wood
  Vils 20-23: wood
  Vil 24:     build mining camp → gold
  Vils 25-26: gold
  Research loom → click Feudal (500 food)
  Feudal: blacksmith + market → click Castle (800 food + 200 gold)
  Castle: 2 extra TCs, mass farms, boom

Each new vil gets a specific job. No reactive eco manager.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..protocol import Technology
from .base import BaseStrategy
from .spatial import PlacementGoal, Position

if TYPE_CHECKING:
    from ..controller import GameController
    from .world import WorldState

logger = logging.getLogger(__name__)

_AGE = {0: "Dark", 1: "Feudal", 2: "Castle", 3: "Imperial"}
_TECH = "_tech_state"

# Build order: vil number → assignment
# "food" = sheep/berries, "wood" = trees, "gold" = gold, "farm" = build farm
_BUILD_ORDER = {
    1: "food", 2: "food", 3: "food", 4: "food", 5: "food", 6: "food",
    7: "build_lc",  # build lumber camp then wood
    8: "wood", 9: "wood", 10: "wood",
    11: "food",  # would be boar lure — we send to sheep/berries
    12: "build_mill",  # build mill near berries then berries
    13: "food", 14: "food", 15: "food", 16: "food",
    17: "farm", 18: "farm",
    19: "wood", 20: "wood", 21: "wood", 22: "wood", 23: "wood",
    24: "build_mc",  # build mining camp then gold
    25: "gold", 26: "gold",
}


class FastCastleStrategy(BaseStrategy):

    def __init__(self, ctrl: GameController):
        super().__init__(ctrl)
        self._tick = 0
        self._scouted = False
        self._built: set[str] = set()
        self._house_cd = 0
        self._farm_cd = 0
        self._feudal_clicked = False
        self._castle_clicked = False
        self._last_vil_count = 0
        self._assigned_vils: set[int] = set()

    @property
    def name(self) -> str:
        return "fast-castle"

    def on_start(self) -> None:
        self.running = True
        logger.info("Fast Castle 27+2 build order started")

    def on_tick(self, raw_state: dict, world: WorldState | None = None) -> str | None:
        if world is None:
            return None
        self._tick += 1
        if self._house_cd > 0:
            self._house_cd -= 1
        if self._farm_cd > 0:
            self._farm_cd -= 1

        w = world
        acts: list[str] = []

        # Scout — manual first sweep then auto
        self._scout(w)

        # Phase 0: build TC (Nomad)
        if not self._has_tc(w, raw_state):
            self._build_tc(w, acts)
            self._log(w, acts)
            return None

        # Always: train vils + houses
        self._train(w, acts)
        self._houses(w, acts)

        # Assign new vils based on build order
        self._assign_by_build_order(w, raw_state, acts)

        # Farms (ongoing after mill)
        if "mill" in self._built:
            self._farms(w, acts)

        # Age-specific goals
        if w.age == 0:
            self._dark(w, raw_state, acts)
        elif w.age == 1:
            self._feudal(w, raw_state, acts)
        elif w.age >= 2:
            self._castle(w, raw_state, acts)

        self._log(w, acts)
        return None

    def is_complete(self, raw_state: dict) -> bool:
        return raw_state.get("age", 0) >= 2 and raw_state.get("villagerCount", 0) >= 35

    # ── Helpers ──

    def _has_tc(self, w: WorldState, raw: dict) -> bool:
        return w.has_building("TOWN_CENTER", complete_only=False) or bool(raw.get("_tcs"))

    def _place(self, name: str, x: float, y: float) -> dict:
        resp = self.ctrl.place_building(name, x, y)
        if resp.get("action") == "error":
            logger.debug("Build %s: %s", name, resp.get("error", "")[:50])
        return resp

    def _ok(self, r: dict) -> bool:
        return r.get("action") != "error"

    def _tc(self, w: WorldState) -> Position:
        return w.spatial.layout.tc_pos or w.spatial.layout.base_center

    def _scan(self, w: WorldState, raw: dict, key: str) -> dict | None:
        return w.nearest_resource_from_scan(raw, key, near=self._tc(w))

    def _find_food_target(self, w: WorldState, raw: dict) -> dict | None:
        """Find best food: sheep near TC > berries near TC."""
        tc = self._tc(w)
        livestock = raw.get("_livestock", {}).get("owned", [])
        near_sheep = [o for o in livestock if tc.distance_to(Position(o["x"], o["y"])) < 15]
        if near_sheep:
            return min(near_sheep, key=lambda o: tc.distance_to(Position(o["x"], o["y"])))
        berries = self._scan(w, raw, "forage")
        if berries and tc.distance_to(Position(berries["x"], berries["y"])) < 15:
            return berries
        return None

    # ── Scout ──

    def _scout(self, w: WorldState) -> None:
        if self._scouted:
            return
        sid = None
        for u in w.units.get_all():
            if u.is_scout:
                sid = u.id
                break
        if not sid:
            return
        msg: dict = {"action": "scout", "unit_id": sid}
        try:
            if self.ctrl.client.request(msg).get("success"):
                self._scouted = True
        except Exception:
            pass

    # ── TC ──

    def _build_tc(self, w: WorldState, acts: list[str]) -> None:
        if not w.can_afford(wood=275, stone=100):
            return
        bc = w.spatial.layout.base_center
        if self._ok(self._place("TOWN_CENTER", bc.x, bc.y)):
            acts.append("tc")

    # ── Train ──

    def _train(self, w: WorldState, acts: list[str]) -> None:
        if not w.tc_is_complete() or w.villager_count >= 40 or w.housing_headroom <= 0 or not w.can_afford(food=50):
            return
        if self._ok(self.ctrl.train_villager()):
            acts.append("tr")

    # ── Houses ──

    def _houses(self, w: WorldState, acts: list[str]) -> None:
        if self._house_cd > 0 or w.housing_headroom > 4 or not w.can_afford(wood=125):
            return
        tc = self._tc(w)
        if self._ok(self._place("HOUSE", tc.x - 4, tc.y + 4)):
            self._house_cd = 8
            acts.append("h")

    # ── Build order assignments ──

    def _assign_by_build_order(self, w: WorldState, raw: dict, acts: list[str]) -> None:
        tc = self._tc(w)

        # Find newly idle vils that haven't been assigned yet
        idle = [u for u in w.idle_vils() if u.id not in self._assigned_vils]
        if not idle:
            return

        vil_num = w.villager_count  # Current vil number in build order

        for u in idle:
            # What should this vil do based on build order?
            assignment = _BUILD_ORDER.get(vil_num, "food" if w.food < w.wood else "wood")

            if assignment == "food":
                target = self._find_food_target(w, raw)
                if target:
                    self.ctrl.attack_target([u.id], target["id"])
                    self._assigned_vils.add(u.id)
                    acts.append(f"v{vil_num}f")

            elif assignment == "wood":
                trees = self._scan(w, raw, "trees")
                if trees:
                    self.ctrl.attack_target([u.id], trees["id"])
                    self._assigned_vils.add(u.id)
                    acts.append(f"v{vil_num}w")

            elif assignment == "gold":
                gold = self._scan(w, raw, "gold")
                if gold:
                    self.ctrl.attack_target([u.id], gold["id"])
                    self._assigned_vils.add(u.id)
                    acts.append(f"v{vil_num}g")

            elif assignment == "farm":
                if self._farm_cd <= 0 and w.can_afford(wood=60):
                    if self._ok(self._place("FARM", tc.x + 3, tc.y)):
                        self._farm_cd = 15
                        self._assigned_vils.add(u.id)
                        acts.append(f"v{vil_num}fm")

            elif assignment == "build_lc":
                if "lc" not in self._built and w.can_afford(wood=100):
                    scan = raw.get("_resources_scan", {})
                    trees_list = scan.get("trees", [])
                    near = [t for t in trees_list if tc.distance_to(Position(t["x"], t["y"])) < 20]
                    if near:
                        safe = w.spatial.layout.safe_side()
                        best = max(near, key=lambda t: (t["x"] - tc.x) * safe.x + (t["y"] - tc.y) * safe.y)
                        tx, ty = best["x"], best["y"]
                        dx, dy = tc.x - tx, tc.y - ty
                        d = max((dx*dx + dy*dy) ** 0.5, 0.1)
                        lx, ly = tx + dx / d * 4, ty + dy / d * 4
                        if self._ok(self._place("LUMBER_CAMP", lx, ly)):
                            self._built.add("lc")
                            # Send this vil to wood
                            self.ctrl.attack_target([u.id], best["id"])
                            self._assigned_vils.add(u.id)
                            acts.append(f"v{vil_num}lc")

            elif assignment == "build_mill":
                if "mill" not in self._built and w.can_afford(wood=100):
                    berries = self._scan(w, raw, "forage")
                    if berries and tc.distance_to(Position(berries["x"], berries["y"])) < 12:
                        bx, by = berries["x"], berries["y"]
                        dx, dy = tc.x - bx, tc.y - by
                        d = max((dx*dx + dy*dy) ** 0.5, 0.1)
                        mx, my = bx + dx / d * 2, by + dy / d * 2
                    else:
                        mx, my = tc.x + 5, tc.y
                    if self._ok(self._place("MILL", mx, my)):
                        self._built.add("mill")
                        if berries:
                            self.ctrl.attack_target([u.id], berries["id"])
                        self._assigned_vils.add(u.id)
                        acts.append(f"v{vil_num}mill")

            elif assignment == "build_mc":
                if "mc" not in self._built and w.can_afford(wood=100):
                    gold = self._scan(w, raw, "gold")
                    if gold:
                        gx, gy = gold["x"], gold["y"]
                        dx, dy = tc.x - gx, tc.y - gy
                        d = max((dx*dx + dy*dy) ** 0.5, 0.1)
                        if self._ok(self._place("MINING_CAMP", gx + dx / d * 3, gy + dy / d * 3)):
                            self._built.add("mc")
                            self.ctrl.attack_target([u.id], gold["id"])
                            self._assigned_vils.add(u.id)
                            acts.append(f"v{vil_num}mc")

            vil_num -= 1  # Assign earlier build order slots to remaining idle

    # ── Farms ──

    def _farms(self, w: WorldState, acts: list[str]) -> None:
        if self._farm_cd > 0 or w.food > 200 or not w.can_afford(wood=60):
            return
        tc = self._tc(w)
        if self._ok(self._place("FARM", tc.x + 3, tc.y)):
            self._farm_cd = 15
            acts.append("fm")

    # ── Dark Age ──

    def _dark(self, w: WorldState, raw: dict, acts: list[str]) -> None:
        tech = raw.get(_TECH, {})
        if not tech.get(str(Technology.LOOM), {}).get("researched") and w.villager_count >= 20 and w.can_afford(food=50):
            if self._ok(self.ctrl.research_loom()):
                acts.append("loom")

        dark_count = sum(1 for b in ["MILL", "LUMBER_CAMP", "MINING_CAMP", "BARRACKS"] if w.has_building(b))
        if not self._feudal_clicked and dark_count >= 2 and w.can_afford(food=500):
            if self._ok(self.ctrl.advance_to_feudal()):
                self._feudal_clicked = True
                acts.append("feudal")

    # ── Feudal ──

    def _feudal(self, w: WorldState, raw: dict, acts: list[str]) -> None:
        tc = self._tc(w)
        if not w.has_building("BLACKSMITH", complete_only=False) and w.can_afford(wood=150):
            if self._ok(self._place("BLACKSMITH", tc.x + 8, tc.y + 4)):
                acts.append("bs")
        if not w.has_building("MARKET", complete_only=False) and w.can_afford(wood=175):
            if self._ok(self._place("MARKET", tc.x - 8, tc.y + 4)):
                acts.append("mkt")

        tech = raw.get(_TECH, {})
        if not tech.get(str(Technology.DOUBLE_BIT_AXE), {}).get("researched") and w.has_building("LUMBER_CAMP"):
            self.ctrl.research(Technology.DOUBLE_BIT_AXE)
        if not tech.get(str(Technology.HORSE_COLLAR), {}).get("researched") and w.has_building("MILL"):
            self.ctrl.research(Technology.HORSE_COLLAR)

        if not self._castle_clicked and w.can_afford(food=800, gold=200) and w.has_building("BLACKSMITH") and w.has_building("MARKET"):
            if self._ok(self.ctrl.advance_to_castle()):
                self._castle_clicked = True
                acts.append("castle")

        self._farms(w, acts)

    # ── Castle ──

    def _castle(self, w: WorldState, raw: dict, acts: list[str]) -> None:
        tc = self._tc(w)
        if w.building_count("TOWN_CENTER") < 2 and w.can_afford(wood=275, stone=100):
            pos = w.spatial.find_placement("TOWN_CENTER", goal=PlacementGoal.NEAR_TC)
            if pos and self._ok(self._place("TOWN_CENTER", pos.x, pos.y)):
                acts.append("tc2")

        if not w.has_building("BARRACKS", complete_only=False) and w.can_afford(wood=175):
            if self._ok(self._place("BARRACKS", tc.x + 10, tc.y - 4)):
                acts.append("rax")

        if not w.has_building("STABLE", complete_only=False) and w.has_building("BARRACKS") and w.can_afford(wood=175):
            if self._ok(self._place("STABLE", tc.x - 10, tc.y - 4)):
                acts.append("stb")

        if w.has_building("STABLE") and w.villager_count >= 25 and w.can_afford(food=120, gold=75):
            if self._ok(self.ctrl.train_knight()):
                acts.append("knt")

        tech = raw.get(_TECH, {})
        if not tech.get(str(Technology.WHEELBARROW), {}).get("researched"):
            self.ctrl.research(Technology.WHEELBARROW)

        self._farms(w, acts)

    # ── Log ──

    def _log(self, w: WorldState, acts: list[str]) -> None:
        m, s = divmod(int(w.game_time), 60)
        a = " ".join(acts) if acts else "-"
        if acts or self._tick % 10 == 0:
            logger.info(
                "[%d:%02d] %s %d/%d F:%.0f W:%.0f G:%.0f S:%.0f i:%d | %s",
                m, s, _AGE.get(w.age, "?"), w.population, w.population + w.housing_headroom,
                w.food, w.wood, w.gold, w.stone, len(w.idle_vils()), a,
            )
