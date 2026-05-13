"""Fast Castle strategy — direct execution, multiple commands per tick.

Tracks actual vil assignments to make informed decisions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..protocol import Technology
from .base import BaseStrategy
from .eco import EcoManager
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
        self._feudal_started = False
        self._castle_started = False
        self._houses_pending = 0
        self._farm_positions: list[tuple[int, int]] = []

    @property
    def name(self) -> str:
        return "fast-castle"

    def on_start(self) -> None:
        self.running = True
        logger.info("FastCastle strategy started")

    def on_tick(self, raw_state: dict, world: WorldState | None = None) -> str | None:
        if world is None:
            return None

        self._tick_count += 1
        w = world
        acts: list[str] = []

        # Decay house pending counter each tick
        if self._houses_pending > 0:
            self._houses_pending -= 1

        self._do_scout(w)

        if not self._has_tc(w, raw_state):
            self._do_build_tc(w, acts)
            self._log(w, acts)
            return None

        self._do_train(w, acts)
        self._do_houses(w, acts)
        self._do_eco_buildings(w, raw_state, acts)
        self._do_assign_idle(w, raw_state, acts)
        self._do_farms(w, raw_state, acts)
        self._do_livestock(w, raw_state, acts)

        if w.age == 0:
            self._do_dark(w, raw_state, acts)
        elif w.age == 1:
            self._do_feudal(w, raw_state, acts)
        elif w.age >= 2:
            self._do_castle(w, raw_state, acts)

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
            logger.warning("Build %s at %.0f,%.0f: %s", name, x, y, resp.get("error", "")[:60])
        return resp

    def _ok(self, resp: dict) -> bool:
        return resp.get("action") != "error"

    def _tc(self, w: WorldState) -> Position:
        return w.spatial.layout.tc_pos or w.spatial.layout.base_center

    def _nearest(self, w: WorldState, raw: dict, res_type: str) -> dict | None:
        return w.nearest_resource_from_scan(raw, res_type, near=self._tc(w))

    def _count_on_resource(self, w: WorldState) -> dict[str, int]:
        """Estimate how many vils are on each resource by checking who's NOT idle."""
        from .units import UnitTask
        all_vils = [u for u in w.units.get_all() if u.is_villager]
        idle = sum(1 for u in all_vils if u.is_idle)
        gathering = len(all_vils) - idle
        # Without per-resource tracking, estimate from desired distribution
        # This is approximate — proper tracking would need resource-target association
        return {"total": len(all_vils), "idle": idle, "working": gathering}

    # ── TC ──

    def _do_build_tc(self, w: WorldState, acts: list[str]) -> None:
        if not w.can_afford(wood=275, stone=100):
            return
        pos = w.spatial.layout.base_center
        if self._ok(self._place("TOWN_CENTER", pos.x, pos.y)):
            acts.append("tc")

    # ── Scout ──

    def _do_scout(self, w: WorldState) -> None:
        if self._scouting_enabled:
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
            resp = self.ctrl.client.request(msg)
            if resp.get("success"):
                self._scouting_enabled = True
                logger.info("Scout enabled (id=%s)", sid)
        except Exception:
            pass

    # ── Train ──

    def _do_train(self, w: WorldState, acts: list[str]) -> None:
        if not w.tc_is_complete():
            return
        if w.villager_count >= self.TARGET_VIL_POP:
            return
        if w.housing_headroom <= 0:
            return
        if not w.can_afford(food=50):
            return
        if self._ok(self.ctrl.train_villager()):
            acts.append("train")

    # ── Houses: only ONE at a time ──

    def _do_houses(self, w: WorldState, acts: list[str]) -> None:
        # Each house gives 5 pop. Only build when actually needed.
        effective_headroom = w.housing_headroom + (self._houses_pending * 5)
        if effective_headroom > 4:
            return
        if not w.can_afford(wood=125):
            return
        tc = self._tc(w)
        if self._ok(self._place("HOUSE", tc.x - 4, tc.y + 4)):
            self._houses_pending += 5  # decays 1 per tick, prevents spam
            acts.append("house")

    # ── Eco buildings ──

    def _do_eco_buildings(self, w: WorldState, raw: dict, acts: list[str]) -> None:
        tc = self._tc(w)

        # Mill near berries — Feudal prereq + farm prereq
        if not w.has_building("MILL", complete_only=False):
            if w.can_afford(wood=100):
                berries = self._nearest(w, raw, "forage")
                if berries:
                    bx, by = berries["x"], berries["y"]
                    dx, dy = tc.x - bx, tc.y - by
                    d = max((dx*dx + dy*dy) ** 0.5, 0.1)
                    mx, my = bx + dx / d * 2, by + dy / d * 2
                    if self._ok(self._place("MILL", mx, my)):
                        acts.append("mill")
                else:
                    if self._ok(self._place("MILL", tc.x + 5, tc.y)):
                        acts.append("mill")
            return  # Don't build LC in same tick — stagger to save wood

        # Lumber camp near trees (only after mill is placed/building)
        if not w.has_building("LUMBER_CAMP", complete_only=False):
            if w.can_afford(wood=100):
                trees = self._nearest(w, raw, "trees")
                if trees:
                    tx, ty = trees["x"], trees["y"]
                    dx, dy = tc.x - tx, tc.y - ty
                    d = max((dx*dx + dy*dy) ** 0.5, 0.1)
                    lx, ly = tx + dx / d * 2, ty + dy / d * 2
                    if self._ok(self._place("LUMBER_CAMP", lx, ly)):
                        acts.append("lc")
                else:
                    if self._ok(self._place("LUMBER_CAMP", tc.x - 5, tc.y)):
                        acts.append("lc")

        # Mining camp near gold — when Feudal or low gold
        if w.age >= 1 or w.gold < 50:
            if not w.has_building("MINING_CAMP", complete_only=False) and w.can_afford(wood=100):
                gold = self._nearest(w, raw, "gold")
                if gold:
                    gx, gy = gold["x"], gold["y"]
                    dx, dy = tc.x - gx, tc.y - gy
                    d = max((dx*dx + dy*dy) ** 0.5, 0.1)
                    if self._ok(self._place("MINING_CAMP", gx + dx / d * 2, gy + dy / d * 2)):
                        acts.append("mc")

    # ── Assign idle vils ──

    def _do_assign_idle(self, w: WorldState, raw: dict, acts: list[str]) -> None:
        idle = w.idle_vils()
        if not idle:
            return

        tc = self._tc(w)
        desired = self.eco.get_desired_distribution_world(w)
        stats = self._count_on_resource(w)
        working = stats["working"]

        # Estimate current workers per resource from desired ratios
        # (since we can't actually track per-resource, estimate proportionally)
        total_desired = sum(desired.values())
        if total_desired == 0:
            return

        # How many SHOULD be on each? And how many idle to send to each?
        food_pct = desired.get("food", 0) / total_desired
        wood_pct = desired.get("wood", 0) / total_desired
        gold_pct = desired.get("gold", 0) / total_desired

        food_workers_est = int(working * food_pct)
        wood_workers_est = int(working * wood_pct)

        food_deficit = max(0, desired.get("food", 0) - food_workers_est)
        wood_deficit = max(0, desired.get("wood", 0) - wood_workers_est)
        gold_deficit = max(0, desired.get("gold", 0))

        # Build assignment targets in deficit order
        targets: list[tuple[str, int, dict | None]] = []

        # Food priority: sheep near TC > berries near TC > DON'T send to distant berries
        livestock = raw.get("_livestock", {}).get("owned", [])
        if food_deficit > 0 and livestock:
            near_tc = [o for o in livestock if tc.distance_to(Position(o["x"], o["y"])) < 10]
            if near_tc:
                targets.append(("food", food_deficit, min(near_tc, key=lambda o: tc.distance_to(Position(o["x"], o["y"])))))
                food_deficit = 0

        # Berries — only if close to TC (< 15 tiles). Otherwise farms are better.
        if food_deficit > 0:
            berries = self._nearest(w, raw, "forage")
            if berries and tc.distance_to(Position(berries["x"], berries["y"])) < 15:
                targets.append(("food", food_deficit, berries))
                food_deficit = 0

        # If still food deficit and no nearby food, don't assign — let _do_farms handle it

        # Wood
        if wood_deficit > 0:
            trees = self._nearest(w, raw, "trees")
            if trees:
                targets.append(("wood", wood_deficit, trees))

        # Gold
        if gold_deficit > 0:
            gold = self._nearest(w, raw, "gold")
            if gold:
                targets.append(("gold", gold_deficit, gold))

        # Assign vils
        remaining = list(idle)
        for res, count, target_obj in targets:
            if not remaining or not target_obj:
                break
            n = min(count, len(remaining))
            tpos = Position(target_obj["x"], target_obj["y"])
            remaining.sort(key=lambda u: u.position.distance_to(tpos))
            batch = remaining[:n]
            remaining = remaining[n:]
            self.ctrl.attack_target([u.id for u in batch], target_obj["id"])
            acts.append(f"{len(batch)}{res[0]}")

        # Leftovers → first target
        if remaining and targets:
            _, _, fallback = targets[0]
            if fallback:
                self.ctrl.attack_target([u.id for u in remaining], fallback["id"])
                acts.append(f"{len(remaining)}x")

    # ── Farms ──

    def _do_farms(self, w: WorldState, raw: dict, acts: list[str]) -> None:
        if not w.has_building("MILL"):
            return

        farm_count = w.building_count("FARM")
        needs_farm = (
            (w.food < 300 and farm_count < w.villager_count // 3)
            or farm_count < max(3, w.villager_count // 4)
        )
        if not needs_farm:
            return
        if not w.can_afford(wood=60):
            return

        # Use smart_build which calls BuildStructureAtTown — handles farm snapping
        resp = self.ctrl.smart_build("FARM", padding=0)
        if self._ok(resp):
            acts.append("farm")
        else:
            # Fallback: try place_building near TC
            tc = self._tc(w)
            self._place("FARM", tc.x + 3, tc.y + 3)

    # ── Livestock ──

    def _do_livestock(self, w: WorldState, raw: dict, acts: list[str]) -> None:
        if not w.tc_is_complete():
            return
        tc = self._tc(w)
        owned = raw.get("_livestock", {}).get("owned", [])
        far = [o for o in owned if Position(o["x"], o["y"]).distance_to(tc) > 8.0]
        if far:
            self.ctrl.move_units([o["id"] for o in far[:4]], tc.x, tc.y)
            acts.append("herd")

    # ── Dark Age ──

    def _do_dark(self, w: WorldState, raw: dict, acts: list[str]) -> None:
        tech = raw.get(_TECH_STATE_KEY, {})

        if not tech.get(str(Technology.LOOM), {}).get("researched") and w.villager_count >= 12 and w.can_afford(food=50):
            if self._ok(self.ctrl.research_loom()):
                acts.append("loom")

        # Feudal — need 2 dark age buildings
        dark_count = sum(1 for b in ["MILL", "LUMBER_CAMP", "MINING_CAMP", "BARRACKS"] if w.has_building(b))
        if not self._feudal_started and dark_count >= 2 and w.can_afford(food=500):
            if self._ok(self.ctrl.advance_to_feudal()):
                self._feudal_started = True
                acts.append("feudal")

    # ── Feudal ──

    def _do_feudal(self, w: WorldState, raw: dict, acts: list[str]) -> None:
        tc = self._tc(w)

        if not w.has_building("BLACKSMITH", complete_only=False) and w.can_afford(wood=150):
            if self._ok(self._place("BLACKSMITH", tc.x + 8, tc.y + 4)):
                acts.append("bs")

        if not w.has_building("MARKET", complete_only=False) and w.can_afford(wood=175):
            if self._ok(self._place("MARKET", tc.x - 8, tc.y + 4)):
                acts.append("mkt")

        tech = raw.get(_TECH_STATE_KEY, {})
        if not tech.get(str(Technology.DOUBLE_BIT_AXE), {}).get("researched") and w.has_building("LUMBER_CAMP"):
            self.ctrl.research(Technology.DOUBLE_BIT_AXE)
        if not tech.get(str(Technology.HORSE_COLLAR), {}).get("researched") and w.has_building("MILL"):
            self.ctrl.research(Technology.HORSE_COLLAR)

        if not self._castle_started and w.can_afford(food=800, gold=200) and w.has_building("BLACKSMITH") and w.has_building("MARKET"):
            if self._ok(self.ctrl.advance_to_castle()):
                self._castle_started = True
                acts.append("castle")

    # ── Castle ──

    def _do_castle(self, w: WorldState, raw: dict, acts: list[str]) -> None:
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

        tech = raw.get(_TECH_STATE_KEY, {})
        if not tech.get(str(Technology.WHEELBARROW), {}).get("researched"):
            self.ctrl.research(Technology.WHEELBARROW)
        if not tech.get(str(Technology.BOW_SAW), {}).get("researched") and w.has_building("LUMBER_CAMP"):
            self.ctrl.research(Technology.BOW_SAW)

    # ── Log ──

    def _log(self, w: WorldState, acts: list[str]) -> None:
        m, s = divmod(int(w.game_time), 60)
        age = _AGE_NAMES.get(w.age, "?")
        idle = len(w.idle_vils())
        cap = w.population + w.housing_headroom
        a = " ".join(acts) if acts else "-"

        if acts or self._tick_count % 10 == 0:
            logger.info(
                "[%d:%02d] %s %d/%d F:%.0f W:%.0f G:%.0f S:%.0f i:%d | %s",
                m, s, age, w.population, cap,
                w.food, w.wood, w.gold, w.stone,
                idle, a,
            )
