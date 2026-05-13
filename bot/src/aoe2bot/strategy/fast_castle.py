"""Fast Castle 27+2 Boom — proper build order with manual scouting.

Phase 0: Scout base perimeter (find trees, berries, gold)
Phase 1: Build TC, split 6 vils (3 sheep, 3 wood)
Phase 2: Follow build order — each new vil gets assigned job
Phase 3: Feudal transition
Phase 4: Castle boom
"""

from __future__ import annotations

import math
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
        self._scout_phase = 0  # 0=perimeter, 1=auto, 2=done
        self._scout_waypoint = 0
        self._scout_id: int | None = None
        self._house_cd = 0
        self._farm_cd = 0
        self._feudal_clicked = False
        self._castle_clicked = False
        self._tc_food_forced = False

        # LOCKED resource locations — once chosen, don't change
        self._wood_target: dict | None = None  # {id, x, y} — the tree we send wood vils to
        self._wood_lc_pos: Position | None = None  # where we built the lumber camp
        self._built: set[str] = set()

    @property
    def name(self) -> str:
        return "fast-castle"

    def on_start(self) -> None:
        self.running = True
        logger.info("Fast Castle 27+2 started")

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

        # Always scout
        self._do_scout(w, acts)

        # No TC → build one + move cows to build site
        if not self._has_tc(w, raw_state):
            self._build_tc(w, acts)
            bc = w.spatial.layout.base_center
            livestock = raw_state.get("_livestock", {}).get("owned", [])
            if livestock:
                self.ctrl.move_units([o["id"] for o in livestock], bc.x, bc.y)
            self._log(w, acts)
            return None

        # TC just completed → FORCE all 6 starting vils to sheep
        if not self._tc_food_forced and w.tc_is_complete():
            food = self._find_food(w, raw_state)
            if food:
                all_vils = [u for u in w.units.get_all() if u.is_villager]
                if all_vils:
                    self.ctrl.attack_target([u.id for u in all_vils], food["id"])
                    acts.append(f"{len(all_vils)}f!")
                    self._tc_food_forced = True

        # TC exists — run build order
        self._train(w, acts)
        self._houses(w, acts)

        # ALL vil assignment goes through one function — strict build order
        self._assign_by_build_order(w, raw_state, acts)

        # Eco buildings at the right time
        self._eco_buildings(w, raw_state, acts)

        # New livestock found by scout → move to TC
        self._handle_new_livestock(w, acts)

        # Farms
        if "mill" in self._built:
            self._farms(w, acts)

        # Age goals
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

    def _place(self, name: str, x: float, y: float, builder_ids: list[int] | None = None) -> dict:
        msg: dict = {"action": "place_building", "building_name": name, "x": x, "y": y}
        if builder_ids:
            msg["builder_ids"] = builder_ids
        resp = self.ctrl.client.request(msg)
        if resp.get("action") == "error":
            logger.debug("Build %s: %s", name, resp.get("error", "")[:50])
        return resp

    def _ok(self, r: dict) -> bool:
        return r.get("action") != "error"

    def _tc(self, w: WorldState) -> Position:
        return w.spatial.layout.tc_pos or w.spatial.layout.base_center

    def _scan(self, w: WorldState, raw: dict, key: str) -> dict | None:
        return w.nearest_resource_from_scan(raw, key, near=self._tc(w))

    # ── Scout: perimeter first, then auto ──

    def _do_scout(self, w: WorldState, acts: list[str]) -> None:
        if self._scout_phase >= 2:
            return

        # Find scout unit
        if self._scout_id is None:
            for u in w.units.get_all():
                if u.is_scout:
                    self._scout_id = u.id
                    break
            if self._scout_id is None:
                return

        if self._scout_phase == 0:
            # Circle around base at radius 15, starting from safe side
            if self._scout_waypoint >= 8:
                self._scout_phase = 1
                return

            if self._tick % 4 != 1:
                return

            base = w.spatial.layout.base_center
            safe = w.spatial.layout.safe_side()
            start_angle = math.atan2(safe.y, safe.x)
            angle = start_angle + (self._scout_waypoint / 8) * 2 * math.pi
            tx = base.x + 15 * math.cos(angle)
            ty = base.y + 15 * math.sin(angle)

            self.ctrl.move_units([self._scout_id], tx, ty)
            self._scout_waypoint += 1
            acts.append(f"sc{self._scout_waypoint}")

        elif self._scout_phase == 1:
            msg: dict = {"action": "scout", "unit_id": self._scout_id}
            try:
                if self.ctrl.client.request(msg).get("success"):
                    self._scout_phase = 2
                    acts.append("auto")
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

    # ── Unified build order — assigns every idle vil by number ──

    def _assign_by_build_order(self, w: WorldState, raw: dict, acts: list[str]) -> None:
        idle = w.idle_vils()
        if not idle:
            return

        tc = self._tc(w)

        # Lock wood location once
        if self._wood_target is None:
            self._pick_wood_location(w, raw)

        food_target = self._find_food(w, raw)

        for u in idle:
            n = w.villager_count

            # Build order assignment
            if n <= 6:
                # Vils 1-6: ALL to food (sheep)
                if food_target:
                    self.ctrl.attack_target([u.id], food_target["id"])
                    acts.append(f"v{n}f")
            elif n <= 10:
                # Vils 7-10: wood
                if self._wood_target:
                    self.ctrl.attack_target([u.id], self._wood_target["id"])
                    acts.append(f"v{n}w")
            elif n <= 18:
                # Vils 11-18: food (sheep/berries)
                if food_target:
                    self.ctrl.attack_target([u.id], food_target["id"])
                    acts.append(f"v{n}f")
            elif n <= 23:
                # Vils 19-23: wood
                if self._wood_target:
                    self.ctrl.attack_target([u.id], self._wood_target["id"])
                    acts.append(f"v{n}w")
            elif n <= 26:
                # Vils 24-26: gold
                gold = self._scan(w, raw, "gold")
                if gold:
                    self.ctrl.attack_target([u.id], gold["id"])
                    acts.append(f"v{n}g")
            else:
                # 27+: balance food/wood
                if w.food < w.wood and food_target:
                    self.ctrl.attack_target([u.id], food_target["id"])
                    acts.append(f"v{n}f")
                elif self._wood_target:
                    self.ctrl.attack_target([u.id], self._wood_target["id"])
                    acts.append(f"v{n}w")

            n -= 1

    def _find_food(self, w: WorldState, raw: dict) -> dict | None:
        tc = self._tc(w)
        livestock = raw.get("_livestock", {}).get("owned", [])
        near = [o for o in livestock if tc.distance_to(Position(o["x"], o["y"])) < 15]
        if near:
            return min(near, key=lambda o: tc.distance_to(Position(o["x"], o["y"])))
        berries = self._scan(w, raw, "forage")
        if berries and tc.distance_to(Position(berries["x"], berries["y"])) < 15:
            return berries
        return None

    def _pick_wood_location(self, w: WorldState, raw: dict) -> None:
        """Pick the best tree cluster and LOCK it. Never change after this."""
        tc = self._tc(w)
        scan = raw.get("_resources_scan", {})
        trees = scan.get("trees", [])

        # Filter to trees within 20 tiles of TC
        near = [t for t in trees if tc.distance_to(Position(t["x"], t["y"])) < 20]
        if not near:
            return

        # Prefer trees on the safe side (toward map edge)
        safe = w.spatial.layout.safe_side()
        best = max(near, key=lambda t: (t["x"] - tc.x) * safe.x + (t["y"] - tc.y) * safe.y)

        self._wood_target = best
        logger.info("LOCKED wood location: %.0f, %.0f", best["x"], best["y"])

    # ── Eco buildings — built at the right vil count ──

    def _eco_buildings(self, w: WorldState, raw: dict, acts: list[str]) -> None:
        tc = self._tc(w)

        # LC at vil 8 (vil 7 sent to wood, by 8 we have wood income)
        if "lc" not in self._built:
            if w.has_building("LUMBER_CAMP", complete_only=False):
                self._built.add("lc")
            elif self._wood_target and w.can_afford(wood=100) and w.villager_count >= 8:
                tx, ty = self._wood_target["x"], self._wood_target["y"]
                dx, dy = tc.x - tx, tc.y - ty
                d = max((dx*dx + dy*dy) ** 0.5, 0.1)
                lx, ly = tx + dx / d * 4, ty + dy / d * 4
                # Find the wood vil closest to trees — use ONLY that one to build
                wood_vils = [u for u in w.units.get_all() if u.is_villager and not u.is_idle]
                near_trees = [u for u in wood_vils if u.position.distance_to(Position(tx, ty)) < 15]
                builder = [near_trees[0].id] if near_trees else None
                if self._ok(self._place("LUMBER_CAMP", lx, ly, builder_ids=builder)):
                    self._built.add("lc")
                    acts.append("lc")

        # Mill at vil 12
        if "mill" not in self._built:
            if w.has_building("MILL", complete_only=False):
                self._built.add("mill")
            elif "lc" in self._built and w.can_afford(wood=100) and w.villager_count >= 12:
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
                    acts.append("mill")

        # Mining camp at vil 24
        if "mc" not in self._built:
            if w.has_building("MINING_CAMP", complete_only=False):
                self._built.add("mc")
            elif w.can_afford(wood=100) and w.villager_count >= 24:
                gold = self._scan(w, raw, "gold")
                if gold:
                    gx, gy = gold["x"], gold["y"]
                    dx, dy = tc.x - gx, tc.y - gy
                    d = max((dx*dx + dy*dy) ** 0.5, 0.1)
                    if self._ok(self._place("MINING_CAMP", gx + dx / d * 3, gy + dy / d * 3)):
                        self._built.add("mc")
                        acts.append("mc")

    # ── New livestock → herd to TC ──

    def _handle_new_livestock(self, w: WorldState, acts: list[str]) -> None:
        if not w.tc_is_complete():
            return
        tc = self._tc(w)
        new = w.units.get_new_units()
        livestock = [u for u in new if u.unit_class == 958]
        if livestock:
            ids = [u.id for u in livestock]
            self.ctrl.move_units(ids, tc.x, tc.y)
            acts.append(f"{len(ids)}cow")

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
        if not tech.get(str(Technology.LOOM), {}).get("researched") and w.villager_count >= 24 and w.can_afford(food=50):
            if self._ok(self.ctrl.research_loom()):
                acts.append("loom")

        dark = sum(1 for b in ["MILL", "LUMBER_CAMP", "MINING_CAMP", "BARRACKS"] if w.has_building(b))
        if not self._feudal_clicked and dark >= 2 and w.can_afford(food=500):
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
