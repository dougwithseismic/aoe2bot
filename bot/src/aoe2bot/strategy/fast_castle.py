"""Fast Castle — sequential build order.

Step-by-step, not reactive. Each step completes before the next starts.
Continuously trains vils and builds houses in the background.
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


class FastCastleStrategy(BaseStrategy):

    def __init__(self, ctrl: GameController):
        super().__init__(ctrl)
        self._tick = 0
        self._scouted = False
        # Track what we've already built (so we don't repeat)
        self._built: set[str] = set()
        self._house_cd = 0
        self._farm_cd = 0
        self._feudal_clicked = False
        self._castle_clicked = False

    @property
    def name(self) -> str:
        return "fast-castle"

    def on_start(self) -> None:
        self.running = True
        logger.info("FastCastle build order started")

    def on_tick(self, raw_state: dict, world: WorldState | None = None) -> str | None:
        if world is None:
            return None
        self._tick += 1
        if self._house_cd > 0:
            self._house_cd -= 1
        if self._farm_cd > 0:
            self._farm_cd -= 1

        w = world
        tc = w.spatial.layout.tc_pos or w.spatial.layout.base_center
        acts: list[str] = []

        # ── Always: scout ──
        self._scout(w)

        # ── Phase 0: no TC → build one ──
        if not self._has_tc(w, raw_state):
            self._build_tc(w, acts)
            self._log(w, acts)
            return None

        # ── Always: train vils ──
        self._train(w, acts)

        # ── Always: houses (one at a time, only when needed) ──
        self._houses(w, acts)

        # ── Build order steps ──
        # Each step checks if it's done. If not, do it and return.
        # This ensures things happen in ORDER.

        # Step 1: Send starting vils to sheep (food under TC)
        if "assign_sheep" not in self._built:
            self._assign_to_sheep(w, raw_state, tc, acts)

        # Step 2: Lumber camp near closest trees on safe side, send 3 vils to wood
        if "lumber_camp" not in self._built:
            self._build_lumber_camp(w, raw_state, tc, acts)

        # Step 3: Mill near berries if close, or near TC for farms
        if "mill" not in self._built and w.villager_count >= 8:
            self._build_mill(w, raw_state, tc, acts)

        # Step 4: Farms (ongoing — build when food < 200, one at a time)
        if "mill" in self._built:
            self._build_farm(w, tc, acts)

        # Step 5: Assign new idle vils — alternate food/wood based on need
        self._assign_new_vils(w, raw_state, tc, acts)

        # Step 6: Dark Age techs + Feudal advance
        if w.age == 0:
            self._dark_age_goals(w, raw_state, acts)
        elif w.age == 1:
            self._feudal_goals(w, raw_state, tc, acts)
        elif w.age >= 2:
            self._castle_goals(w, raw_state, tc, acts)

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

    def _nearest_scan(self, w: WorldState, raw: dict, key: str) -> dict | None:
        tc = self._tc(w)
        return w.nearest_resource_from_scan(raw, key, near=tc)

    # ── Scout ──

    def _scout(self, w: WorldState) -> None:
        if self._scouted:
            return
        sid = None
        for u in w.units.get_all():
            if u.is_scout:
                sid = u.id
                break
        msg: dict = {"action": "scout"}
        if sid:
            msg["unit_id"] = sid
        try:
            if self.ctrl.client.request(msg).get("success"):
                self._scouted = True
        except Exception:
            pass

    # ── TC ──

    def _build_tc(self, w: WorldState, acts: list[str]) -> None:
        if not w.can_afford(wood=275, stone=100):
            return
        if self._ok(self._place("TOWN_CENTER", w.spatial.layout.base_center.x, w.spatial.layout.base_center.y)):
            acts.append("tc")

    # ── Train ──

    def _train(self, w: WorldState, acts: list[str]) -> None:
        if not w.tc_is_complete() or w.villager_count >= 40 or w.housing_headroom <= 0 or not w.can_afford(food=50):
            return
        if self._ok(self.ctrl.train_villager()):
            acts.append("tr")

    # ── Houses ──

    def _houses(self, w: WorldState, acts: list[str]) -> None:
        if self._house_cd > 0:
            return
        if w.housing_headroom > 4:
            return
        if not w.can_afford(wood=125):
            return
        tc = self._tc(w)
        if self._ok(self._place("HOUSE", tc.x - 4, tc.y + 4)):
            self._house_cd = 8
            acts.append("h")

    # ── Step 1: Sheep ──

    def _assign_to_sheep(self, w: WorldState, raw: dict, tc: Position, acts: list[str]) -> None:
        if not w.tc_is_complete():
            return
        idle = w.idle_vils()
        if not idle:
            self._built.add("assign_sheep")
            return

        livestock = raw.get("_livestock", {}).get("owned", [])
        if livestock:
            near = [o for o in livestock if tc.distance_to(Position(o["x"], o["y"])) < 15]
            if near:
                target = min(near, key=lambda o: tc.distance_to(Position(o["x"], o["y"])))
                ids = [u.id for u in idle[:6]]
                self.ctrl.attack_target(ids, target["id"])
                acts.append(f"{len(ids)}sh")
                self._built.add("assign_sheep")
                return

        # No sheep — send to berries
        berries = self._nearest_scan(w, raw, "forage")
        if berries and tc.distance_to(Position(berries["x"], berries["y"])) < 15:
            ids = [u.id for u in idle[:6]]
            self.ctrl.attack_target(ids, berries["id"])
            acts.append(f"{len(ids)}f")
        self._built.add("assign_sheep")

    # ── Step 2: Lumber camp ──

    def _build_lumber_camp(self, w: WorldState, raw: dict, tc: Position, acts: list[str]) -> None:
        if w.has_building("LUMBER_CAMP", complete_only=False):
            self._built.add("lumber_camp")
            return
        if not w.can_afford(wood=100):
            return

        # Find closest trees to TC (within 20 tiles), prefer safe side
        scan = raw.get("_resources_scan", {})
        trees = scan.get("trees", [])
        near = [t for t in trees if tc.distance_to(Position(t["x"], t["y"])) < 20]

        if not near:
            return  # Wait for scout to find trees

        safe = w.spatial.layout.safe_side()
        # Pick trees on safe side of TC
        best = max(near, key=lambda t: (t["x"] - tc.x) * safe.x + (t["y"] - tc.y) * safe.y)
        tx, ty = best["x"], best["y"]

        # Place LC 4 tiles from trees toward TC (2 was too close — still in treeline)
        dx, dy = tc.x - tx, tc.y - ty
        d = max((dx*dx + dy*dy) ** 0.5, 0.1)
        lx, ly = tx + dx / d * 4, ty + dy / d * 4

        if self._ok(self._place("LUMBER_CAMP", lx, ly)):
            self._built.add("lumber_camp")
            acts.append("lc")

            # Send 3 vils to these trees
            idle = w.idle_vils()
            if len(idle) >= 3:
                closest = sorted(idle, key=lambda u: u.position.distance_to(Position(tx, ty)))[:3]
                self.ctrl.attack_target([u.id for u in closest], best["id"])
                acts.append("3w")

    # ── Step 3: Mill ──

    def _build_mill(self, w: WorldState, raw: dict, tc: Position, acts: list[str]) -> None:
        if w.has_building("MILL", complete_only=False):
            self._built.add("mill")
            return
        if not w.can_afford(wood=100):
            return

        # Place near berries if close, otherwise near TC for farms
        berries = self._nearest_scan(w, raw, "forage")
        if berries and tc.distance_to(Position(berries["x"], berries["y"])) < 12:
            bx, by = berries["x"], berries["y"]
            dx, dy = tc.x - bx, tc.y - by
            d = max((dx*dx + dy*dy) ** 0.5, 0.1)
            mx, my = bx + dx / d * 2, by + dy / d * 2
        else:
            mx, my = tc.x + 5, tc.y

        if self._ok(self._place("MILL", mx, my)):
            self._built.add("mill")
            acts.append("mill")

    # ── Step 4: Farms ──

    def _build_farm(self, w: WorldState, tc: Position, acts: list[str]) -> None:
        if self._farm_cd > 0:
            return
        if w.food > 200:
            return
        if not w.can_afford(wood=60):
            return

        if self._ok(self._place("FARM", tc.x + 3, tc.y)):
            self._farm_cd = 15
            acts.append("fm")

    # ── Step 5: Assign new idle vils ──

    def _assign_new_vils(self, w: WorldState, raw: dict, tc: Position, acts: list[str]) -> None:
        idle = w.idle_vils()
        if not idle:
            return

        # Simple rule: if food < wood, send to food. Otherwise wood.
        if w.food < w.wood:
            # Food: sheep > berries (close) > nothing (wait for farm)
            livestock = raw.get("_livestock", {}).get("owned", [])
            near_sheep = [o for o in livestock if tc.distance_to(Position(o["x"], o["y"])) < 15]
            if near_sheep:
                target = min(near_sheep, key=lambda o: tc.distance_to(Position(o["x"], o["y"])))
                for u in idle:
                    self.ctrl.attack_target([u.id], target["id"])
                acts.append(f"{len(idle)}sh")
                return

            berries = self._nearest_scan(w, raw, "forage")
            if berries and tc.distance_to(Position(berries["x"], berries["y"])) < 15:
                for u in idle:
                    self.ctrl.attack_target([u.id], berries["id"])
                acts.append(f"{len(idle)}f")
                return
        else:
            # Wood: send to nearest trees
            trees = self._nearest_scan(w, raw, "trees")
            if trees:
                tpos = Position(trees["x"], trees["y"])
                closest = sorted(idle, key=lambda u: u.position.distance_to(tpos))
                for u in closest:
                    self.ctrl.attack_target([u.id], trees["id"])
                acts.append(f"{len(idle)}w")
                return

    # ── Dark Age ──

    def _dark_age_goals(self, w: WorldState, raw: dict, acts: list[str]) -> None:
        tech = raw.get(_TECH, {})

        if not tech.get(str(Technology.LOOM), {}).get("researched") and w.villager_count >= 12 and w.can_afford(food=50):
            if self._ok(self.ctrl.research_loom()):
                acts.append("loom")

        dark_count = sum(1 for b in ["MILL", "LUMBER_CAMP", "MINING_CAMP", "BARRACKS"] if w.has_building(b))
        if not self._feudal_clicked and dark_count >= 2 and w.can_afford(food=500):
            if self._ok(self.ctrl.advance_to_feudal()):
                self._feudal_clicked = True
                acts.append("feudal")

    # ── Feudal ──

    def _feudal_goals(self, w: WorldState, raw: dict, tc: Position, acts: list[str]) -> None:
        if not w.has_building("BLACKSMITH", complete_only=False) and w.can_afford(wood=150):
            if self._ok(self._place("BLACKSMITH", tc.x + 8, tc.y + 4)):
                acts.append("bs")

        if not w.has_building("MARKET", complete_only=False) and w.can_afford(wood=175):
            if self._ok(self._place("MARKET", tc.x - 8, tc.y + 4)):
                acts.append("mkt")

        # Mining camp for gold
        if not w.has_building("MINING_CAMP", complete_only=False) and w.can_afford(wood=100):
            gold = self._nearest_scan(w, raw, "gold")
            if gold:
                gx, gy = gold["x"], gold["y"]
                dx, dy = tc.x - gx, tc.y - gy
                d = max((dx*dx + dy*dy) ** 0.5, 0.1)
                if self._ok(self._place("MINING_CAMP", gx + dx / d * 2, gy + dy / d * 2)):
                    acts.append("mc")

        tech = raw.get(_TECH, {})
        if not tech.get(str(Technology.DOUBLE_BIT_AXE), {}).get("researched") and w.has_building("LUMBER_CAMP"):
            self.ctrl.research(Technology.DOUBLE_BIT_AXE)
        if not tech.get(str(Technology.HORSE_COLLAR), {}).get("researched") and w.has_building("MILL"):
            self.ctrl.research(Technology.HORSE_COLLAR)

        if not self._castle_clicked and w.can_afford(food=800, gold=200) and w.has_building("BLACKSMITH") and w.has_building("MARKET"):
            if self._ok(self.ctrl.advance_to_castle()):
                self._castle_clicked = True
                acts.append("castle")

        self._build_farm(w, tc, acts)

    # ── Castle ──

    def _castle_goals(self, w: WorldState, raw: dict, tc: Position, acts: list[str]) -> None:
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

        self._build_farm(w, tc, acts)

    # ── Log ──

    def _log(self, w: WorldState, acts: list[str]) -> None:
        m, s = divmod(int(w.game_time), 60)
        age = _AGE.get(w.age, "?")
        a = " ".join(acts) if acts else "-"
        if acts or self._tick % 10 == 0:
            logger.info(
                "[%d:%02d] %s %d/%d F:%.0f W:%.0f G:%.0f S:%.0f i:%d | %s",
                m, s, age, w.population, w.population + w.housing_headroom,
                w.food, w.wood, w.gold, w.stone,
                len(w.idle_vils()), a,
            )
