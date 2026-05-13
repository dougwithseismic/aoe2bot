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
        self._assigned_vils: set[int] = set()
        self._vils_split = False

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

        # No TC → build one
        if not self._has_tc(w, raw_state):
            self._build_tc(w, acts)
            self._log(w, acts)
            return None

        # TC exists — run build order
        self._train(w, acts)
        self._houses(w, acts)

        # Immediately split starting vils: 3 food, 3 wood
        if not self._vils_split and w.tc_is_complete():
            self._split_starting_vils(w, raw_state, acts)

        # Build eco buildings when we can
        self._eco_buildings(w, raw_state, acts)

        # Assign new idle vils by build order number
        self._assign_new_vils(w, raw_state, acts)

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
            # Manual scout toward fog of war — prioritize safe side (map edge)
            if self._scout_waypoint >= 6:
                self._scout_phase = 1
                return

            if self._tick % 5 != 1:
                return

            base = w.spatial.layout.base_center
            safe = w.spatial.layout.safe_side()

            # Find unexplored direction from MapKnowledge
            unexplored = w.map.get_unexplored_direction(base)

            if unexplored is not None:
                # Bias toward safe side
                dx = unexplored.x + safe.x * 0.5
                dy = unexplored.y + safe.y * 0.5
                d = max((dx*dx + dy*dy) ** 0.5, 0.1)
                radius = 12 + self._scout_waypoint * 4
                tx = base.x + dx / d * radius
                ty = base.y + dy / d * radius
            else:
                # Everything explored nearby — expand outward on safe side
                radius = 15 + self._scout_waypoint * 5
                tx = base.x + safe.x * radius
                ty = base.y + safe.y * radius

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

    # ── Split starting 6 vils: 3 food, 3 wood ──

    def _split_starting_vils(self, w: WorldState, raw: dict, acts: list[str]) -> None:
        # Grab ALL vils (not just idle) — VilOcc may have assigned them to wrong things
        all_vils = [u for u in w.units.get_all() if u.is_villager]
        if len(all_vils) < 3:
            return

        tc = self._tc(w)

        # Find food target (sheep near TC)
        food_target = self._find_food(w, raw)

        # Find and LOCK wood target (closest trees on safe side)
        if self._wood_target is None:
            self._pick_wood_location(w, raw)

        if not food_target and not self._wood_target:
            return  # Scout hasn't found anything yet

        # Sort all vils by distance to TC
        all_vils.sort(key=lambda u: u.position.distance_to(tc))

        # Standard FC: 6 on food first, then wood. Starting split = all 6 to food
        # (vil 7 is first wood vil — comes from training, not the starting 6)
        food_count = len(all_vils)  # ALL starting vils to food
        if food_target:
            food_batch = all_vils[:food_count]
            self.ctrl.attack_target([u.id for u in food_batch], food_target["id"])
            for u in food_batch:
                self._assigned_vils.add(u.id)
            acts.append(f"{food_count}f!")

        if self._wood_target:
            wood_batch = all_vils[food_count:]
            if wood_batch:
                self.ctrl.attack_target([u.id for u in wood_batch], self._wood_target["id"])
                for u in wood_batch:
                    self._assigned_vils.add(u.id)
                acts.append(f"{len(wood_batch)}w!")

        self._vils_split = True
        logger.info("Split %d vils: %d food, %d wood", len(all_vils), food_count, len(all_vils) - food_count)

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

    # ── Eco buildings ──

    def _eco_buildings(self, w: WorldState, raw: dict, acts: list[str]) -> None:
        tc = self._tc(w)

        # Lumber camp at locked wood location
        if "lc" not in self._built and self._wood_target and w.can_afford(wood=100):
            if not w.has_building("LUMBER_CAMP", complete_only=False):
                tx, ty = self._wood_target["x"], self._wood_target["y"]
                dx, dy = tc.x - tx, tc.y - ty
                d = max((dx*dx + dy*dy) ** 0.5, 0.1)
                lx, ly = tx + dx / d * 4, ty + dy / d * 4
                if self._ok(self._place("LUMBER_CAMP", lx, ly)):
                    self._built.add("lc")
                    self._wood_lc_pos = Position(lx, ly)
                    acts.append("lc")
            else:
                self._built.add("lc")

        # Mill — at vil 12 (after LC, need berries)
        if "mill" not in self._built and "lc" in self._built and w.villager_count >= 12:
            if not w.has_building("MILL", complete_only=False) and w.can_afford(wood=100):
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
            else:
                self._built.add("mill")

        # Mining camp — when we need gold (Feudal prep or low gold)
        if "mc" not in self._built and w.villager_count >= 22:
            if not w.has_building("MINING_CAMP", complete_only=False) and w.can_afford(wood=100):
                gold = self._scan(w, raw, "gold")
                if gold:
                    gx, gy = gold["x"], gold["y"]
                    dx, dy = tc.x - gx, tc.y - gy
                    d = max((dx*dx + dy*dy) ** 0.5, 0.1)
                    if self._ok(self._place("MINING_CAMP", gx + dx / d * 3, gy + dy / d * 3)):
                        self._built.add("mc")
                        acts.append("mc")
            else:
                self._built.add("mc")

    # ── Assign new vils by build order ──

    def _assign_new_vils(self, w: WorldState, raw: dict, acts: list[str]) -> None:
        # Check ALL idle vils every tick — reassign if resource depleted
        idle = w.idle_vils()
        if not idle:
            return

        n = w.villager_count

        for u in idle:
            # 27+2 Fast Castle build order:
            #  1-6:  food (sheep)         — starting vils, handled by _split
            #  7:    wood (build LC)      — first wood vil
            #  8-10: wood                 — 4 on wood total
            #  11:   food (lure boar)     — we send to sheep/berries
            #  12:   food (build mill)    — then berries
            #  13-16: food (berries)      — ~11 on food total
            #  17-18: food (farms)        — transition to farms
            #  19:   wood (2nd LC)        — 5 more on wood
            #  20-23: wood                — 9 on wood total
            #  24:   gold (build MC)      — gold for Castle
            #  25-26: gold                — 3 on gold total
            if n <= 6:
                job = "food"
            elif n <= 10:
                job = "wood"    # vils 7-10: wood (4 total)
            elif n <= 18:
                job = "food"    # vils 11-18: food (sheep/berries/farms)
            elif n <= 23:
                job = "wood"    # vils 19-23: wood (9 total)
            elif n <= 26:
                job = "gold"    # vils 24-26: gold (3 total)
            else:
                job = "food" if w.food < w.wood else "wood"

            assigned = False
            if job == "food":
                target = self._find_food(w, raw)
                if target:
                    self.ctrl.attack_target([u.id], target["id"])
                    assigned = True
                    acts.append(f"v{n}f")
            elif job == "wood":
                if self._wood_target:
                    self.ctrl.attack_target([u.id], self._wood_target["id"])
                    assigned = True
                    acts.append(f"v{n}w")
            elif job == "gold":
                gold = self._scan(w, raw, "gold")
                if gold:
                    self.ctrl.attack_target([u.id], gold["id"])
                    assigned = True
                    acts.append(f"v{n}g")

            n -= 1

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
