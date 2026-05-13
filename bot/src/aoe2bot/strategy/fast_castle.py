"""Fast Castle strategy -- phase-based approach with robust error handling.

Phase 0: Build TC (Nomad only) -- nothing else fires until TC is placing
Phase 1: Early Dark Age (TC exists, < 10 vils) -- scout, train, eco basics
Phase 2: Dark Age Boom (10-20 vils) -- farms, loom, advance to Feudal
Phase 3: Feudal Age -- blacksmith + market, eco upgrades, advance to Castle
Phase 4: Castle Age Boom -- extra TCs, mass farms, military
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..protocol import Technology
from .actions import Priority
from .base import BaseStrategy
from .eco import DropoffNeeded, EcoManager, VilAssignment
from .event_queue import QueuedAction
from .spatial import PlacementGoal, Position

if TYPE_CHECKING:
    from ..controller import GameController
    from .world import WorldState

logger = logging.getLogger(__name__)

# Age name lookup
_AGE_NAMES = {0: "Dark", 1: "Feudal", 2: "Castle", 3: "Imperial"}

# Tech IDs we check from raw_state's _tech_state cache
_TECH_STATE_KEY = "_tech_state"


class FastCastleStrategy(BaseStrategy):
    """Phase-based Fast Castle -- clear phase gates, error-checked builds.

    All state queries go through WorldState.
    All commands go through EventQueue as QueuedActions.
    The runner calls world.queue.tick() AFTER on_tick to execute one command.

    Phase transitions:
      0 -> 1: TC exists (building or complete)
      1 -> 2: 10+ villagers
      2 -> 3: Feudal Age reached
      3 -> 4: Castle Age reached
    """

    TARGET_VIL_POP = 40
    COMPLETE_POP = 50

    def __init__(self, ctrl: GameController):
        super().__init__(ctrl)
        self.eco = EcoManager()
        self._tick_count = 0
        self._scouting_enabled = False
        self._last_logged_action: str | None = None
        self._last_raw: dict = {}

    @property
    def name(self) -> str:
        return "fast-castle"

    def on_start(self) -> None:
        self.running = True
        logger.info("FastCastle strategy started (phase-based)")

    def on_tick(self, raw_state: dict, world: WorldState | None = None) -> str | None:
        if world is None:
            return None

        self._last_raw = raw_state
        self._tick_count += 1
        w = world

        phase = self._get_phase(w)

        if phase == 0:
            self._phase_0_build_tc(w)
            # Do NOTHING else until TC is placing
            queued_name = self._log_tick(w)
            return queued_name

        # -- Scouting: call directly every tick until it succeeds --
        self._ensure_scouting(w)

        # -- Always: housing + train vils --
        self._eval_housing(w)
        self._eval_train_villager(w)

        # -- Always: assign idle vils (phase-aware) --
        self._eval_idle_vils(w, raw_state)

        # -- Always: livestock --
        self._eval_livestock(w, raw_state)

        # -- Phase-specific goals --
        if phase == 1:
            self._phase_1_early_dark(w, raw_state)
        elif phase == 2:
            self._phase_2_dark_boom(w, raw_state)
        elif phase == 3:
            self._phase_3_feudal(w, raw_state)
        elif phase >= 4:
            self._phase_4_castle_boom(w, raw_state)

        queued_name = self._log_tick(w)
        return queued_name

    def is_complete(self, raw_state: dict) -> bool:
        age = raw_state.get("age", 0)
        vil_count = raw_state.get("villagerCount", 0)
        pop = raw_state.get("population", {}).get("current", 0)
        return age >= 2 and vil_count >= 35 and pop >= self.COMPLETE_POP

    # ================================================================
    # Phase detection
    # ================================================================

    def _get_phase(self, w: WorldState) -> int:
        if not self._has_tc(w):
            return 0
        if w.age == 0 and w.villager_count < 10:
            return 1
        if w.age == 0:
            return 2
        if w.age == 1:
            return 3
        return 4

    def _has_tc(self, w: WorldState) -> bool:
        """Robust TC detection via building tracker or get_town_centers data.

        Does NOT use spatial.layout.tc_pos because that's inferred from
        vil positions when no TC exists (Nomad starts).
        """
        if w.has_building("TOWN_CENTER", complete_only=False):
            return True
        # Check raw TC data from get_town_centers enrichment
        tcs = self._last_raw.get("_tcs", [])
        if tcs:
            return True
        return False

    # ================================================================
    # Logging
    # ================================================================

    def _log_tick(self, w: WorldState) -> str | None:
        """Log one line per tick: state + what was queued."""
        sequences = w.queue.get_active_sequences()
        standalone_names: list[str] = []

        for act in w.queue._standalone:
            standalone_names.append(act.name)
        for seq in sequences:
            step = seq.current
            if step is not None:
                standalone_names.append(f"{seq.name}:{step.name}")

        queued_desc = standalone_names[0] if standalone_names else None

        m, s = divmod(int(w.game_time), 60)
        age_name = _AGE_NAMES.get(w.age, f"?{w.age}")
        idle_count = len(w.idle_vils())
        pop_cap = w.population + w.housing_headroom
        phase = self._get_phase(w)

        if queued_desc and queued_desc != self._last_logged_action:
            logger.info(
                "[%d:%02d] %s P%d | Pop %d/%d | F:%.0f W:%.0f G:%.0f S:%.0f | Idle:%d | -> %s",
                m, s,
                age_name, phase,
                w.population, pop_cap,
                w.food, w.wood, w.gold, w.stone,
                idle_count,
                queued_desc,
            )
            self._last_logged_action = queued_desc
        elif self._tick_count % 10 == 0:
            logger.info(
                "[%d:%02d] %s P%d | Pop %d/%d | F:%.0f W:%.0f G:%.0f S:%.0f | Idle:%d",
                m, s,
                age_name, phase,
                w.population, pop_cap,
                w.food, w.wood, w.gold, w.stone,
                idle_count,
            )
        return queued_desc

    # ================================================================
    # Placement helpers -- builds QueuedActions with error checking
    # ================================================================

    def _make_build_action(
        self,
        name: str,
        building: str,
        w: WorldState,
        priority: int,
        goal: PlacementGoal = PlacementGoal.NEAR_TC,
        near: Position | None = None,
        building_name_override: str | None = None,
    ) -> QueuedAction:
        """Create a QueuedAction that finds a spot via spatial and places a building.

        Every build response is checked for errors -- on failure the command
        is NOT registered with CommandTracker.
        """
        ctrl = self.ctrl
        place_name = building_name_override or building

        def execute() -> dict:
            pos = w.spatial.find_placement(building, goal=goal, near=near)
            if pos is None:
                resp = ctrl.smart_build(place_name, padding=0)
            else:
                resp = ctrl.place_building(place_name, pos.x, pos.y)

            if resp.get("action") == "error":
                logger.warning("Build %s failed: %s", name, resp.get("error"))
                return resp

            # Only register on success
            if pos is not None:
                w.commands.issue(
                    "BUILD",
                    target_position=pos,
                    building_type=building,
                    game_time=w.game_time,
                    key=name,
                )
            return resp

        return QueuedAction(name=name, priority=priority, execute=execute)

    def _make_train_action(
        self,
        name: str,
        w: WorldState,
        priority: int,
        train_fn,
    ) -> QueuedAction:
        """Create a QueuedAction that trains a unit and registers the command."""
        def execute() -> dict:
            resp = train_fn()
            if resp.get("action") == "error":
                logger.warning("Train %s failed: %s", name, resp.get("error"))
                return resp
            w.commands.issue("TRAIN", game_time=w.game_time, key=name)
            return resp

        return QueuedAction(name=name, priority=priority, execute=execute)

    def _make_research_action(
        self,
        name: str,
        w: WorldState,
        priority: int,
        research_fn,
    ) -> QueuedAction:
        """Create a QueuedAction that researches a tech and registers the command."""
        def execute() -> dict:
            resp = research_fn()
            if resp.get("action") == "error":
                logger.warning("Research %s failed: %s", name, resp.get("error"))
                return resp
            w.commands.issue("RESEARCH", game_time=w.game_time, key=name)
            return resp

        return QueuedAction(name=name, priority=priority, execute=execute)

    # ================================================================
    # Phase 0: Build TC (Nomad)
    # ================================================================

    def _phase_0_build_tc(self, w: WorldState) -> None:
        """Place TC at villager centroid. Do nothing else until TC is building."""
        # Already queued?
        if w.queue.has_active("build_tc"):
            logger.debug("Waiting for TC construction...")
            return

        # Already issued and waiting for acknowledgement?
        if not w.commands.can_issue("BUILD", "build_tc"):
            logger.debug("Waiting for TC construction...")
            return

        if not w.can_afford(wood=275, stone=100):
            logger.debug("Cannot afford TC yet (need 275W 100S)")
            return

        ctrl = self.ctrl
        pos = w.spatial.layout.base_center

        def build_tc(p=pos) -> dict:
            logger.info("Placing TC at %.1f, %.1f", p.x, p.y)
            resp = ctrl.place_building("TOWN_CENTER", p.x, p.y)
            logger.info("TC place response: %s", resp)
            if resp.get("action") == "error":
                logger.warning("TC placement FAILED: %s", resp.get("error"))
                return resp
            w.commands.issue(
                "BUILD", target_position=p, building_type="TOWN_CENTER",
                game_time=w.game_time, key="build_tc",
            )
            return resp

        w.queue.add_action(QueuedAction(
            name="build_tc",
            priority=Priority.CRITICAL,
            execute=build_tc,
        ))

    # ================================================================
    # Scouting -- called directly every tick, not via queue
    # ================================================================

    def _ensure_scouting(self, w: WorldState) -> None:
        """Enable auto-scouting. Called every tick until it succeeds."""
        if self._scouting_enabled:
            return

        scout_id: int | None = None
        for u in w.units.get_all():
            if u.is_scout:
                scout_id = u.id
                break

        msg: dict = {"action": "scout"}
        if scout_id is not None:
            msg["unit_id"] = scout_id

        try:
            resp = self.ctrl.client.request(msg)
            if resp.get("success"):
                self._scouting_enabled = True
                logger.info("Auto-scout enabled (unit=%s)", scout_id)
        except Exception as exc:
            logger.debug("Scout request failed: %s", exc)

    # ================================================================
    # Housing -- always active (phases 1-4)
    # ================================================================

    def _eval_housing(self, w: WorldState) -> None:
        """Build houses based on headroom. Prevent spam via CommandTracker."""
        if not w.can_afford(wood=25):
            return
        if not w.commands.can_issue("BUILD", "HOUSE"):
            return
        if w.queue.has_active("build_house"):
            return

        if w.housing_headroom <= 1:
            prio = Priority.CRITICAL
        elif w.housing_headroom <= 3:
            prio = Priority.HIGH
        elif w.housing_headroom <= 5 and w.villager_count >= 10:
            prio = Priority.NORMAL
        else:
            return

        w.queue.add_action(self._make_build_action(
            "build_house", "HOUSE", w, prio,
        ))

    # ================================================================
    # Train villager -- always active (phases 1-4)
    # ================================================================

    def _eval_train_villager(self, w: WorldState) -> None:
        """Train a villager if TC exists, not pop-blocked, under target."""
        if not w.tc_is_complete():
            return
        if w.villager_count >= self.TARGET_VIL_POP:
            return
        if w.housing_headroom <= 0:
            return
        if not w.can_afford(food=50):
            return
        if not w.commands.can_issue("TRAIN", "villager"):
            return
        if w.queue.has_active("train_villager"):
            return

        w.queue.add_action(self._make_train_action(
            "train_villager", w, Priority.URGENT, lambda: self.ctrl.train_villager(),
        ))

    # ================================================================
    # Idle vil assignment -- phases 1-4 (eco manager integration)
    # ================================================================

    def _eval_idle_vils(self, w: WorldState, raw_state: dict) -> None:
        """Assign idle vils to the most-needed resource, or build a drop-off.

        Handles all three eco manager return types:
          - VilAssignment: send vils to gather
          - DropoffNeeded: build drop-off (with CommandTracker check)
          - None: nothing to do
        """
        idle = w.idle_vils()
        if not idle:
            return

        skip_resources: set[str] = set()

        for _ in range(4):
            result = self.eco.get_idle_assignment_world(
                w, raw_state, skip_resources=skip_resources,
            )
            if result is None:
                return

            if isinstance(result, DropoffNeeded):
                dropoff_key = f"dropoff_{result.resource}"
                # Check BOTH queue AND command tracker to prevent spam
                if (w.queue.has_active(f"build_dropoff_{result.resource}")
                        or not w.commands.can_issue("BUILD", dropoff_key)):
                    skip_resources.add(result.resource)
                    continue
                if not w.can_afford(wood=100):
                    skip_resources.add(result.resource)
                    continue

                ctrl = self.ctrl
                btype = result.building_type
                near = result.near

                def build_dropoff(b=btype, n=near, r=result.resource) -> dict:
                    resp = ctrl.place_building(b, n.x, n.y)
                    if resp.get("action") == "error":
                        logger.warning("Dropoff %s build failed: %s", b, resp.get("error"))
                        return resp
                    w.commands.issue(
                        "BUILD", target_position=n, building_type=b,
                        game_time=w.game_time, key=f"dropoff_{r}",
                    )
                    return resp

                w.queue.add_action(QueuedAction(
                    name=f"build_dropoff_{result.resource}",
                    priority=Priority.HIGH,
                    execute=build_dropoff,
                ))
                return

            if isinstance(result, VilAssignment):
                ctrl = self.ctrl
                vil_ids = result.vil_ids
                target_id = result.target_id
                resource = result.resource

                def execute(vids=vil_ids, tid=target_id, res=resource) -> dict:
                    resp = ctrl.attack_target(vids, tid)
                    w.commands.issue(
                        "GATHER", unit_ids=vids, target_id=tid,
                        game_time=w.game_time, key=f"gather_{res}",
                    )
                    return resp

                w.queue.add_action(QueuedAction(
                    name=f"assign_vils_{resource}",
                    priority=Priority.HIGH,
                    execute=execute,
                ))
                return

    # ================================================================
    # Livestock -- always active when TC exists
    # ================================================================

    def _eval_livestock(self, w: WorldState, raw_state: dict) -> None:
        """Send owned livestock (sheep/goats) to TC for food."""
        if not w.tc_is_complete():
            return
        if w.queue.has_active("herd_livestock"):
            return

        livestock = raw_state.get("_livestock", {})
        owned = livestock.get("owned", [])
        if not owned:
            return

        tc_pos = w.spatial.layout.tc_pos
        if tc_pos is None:
            return

        far_livestock = [
            obj for obj in owned
            if Position(obj["x"], obj["y"]).distance_to(tc_pos) > 5.0
        ]
        if not far_livestock:
            return

        ctrl = self.ctrl
        ids = [obj["id"] for obj in far_livestock[:4]]

        def herd() -> dict:
            return ctrl.move_units(ids, tc_pos.x, tc_pos.y)

        w.queue.add_action(QueuedAction(
            name="herd_livestock",
            priority=Priority.HIGH,
            execute=herd,
        ))

    # ================================================================
    # Phase 1: Early Dark Age (TC exists, < 10 vils)
    # ================================================================

    def _phase_1_early_dark(self, w: WorldState, raw_state: dict) -> None:
        """Scout is already running. Focus on vil production and first eco buildings.

        Eco buildings (mill, lumber camp) are handled by the eco manager's
        DropoffNeeded logic -- we don't manually queue them here. The eco
        manager only fires when idle vils exist AND resources have been
        scouted, so we don't send vils to nonexistent resources.
        """
        # Nothing phase-specific beyond what on_tick already does:
        # scouting, housing, training, idle vil assignment.
        # Eco manager handles mill/lumber camp via DropoffNeeded when
        # idle vils need a drop-off point.
        pass

    # ================================================================
    # Phase 2: Dark Age Boom (10-20 vils)
    # ================================================================

    def _phase_2_dark_boom(self, w: WorldState, raw_state: dict) -> None:
        """Farms, loom, Feudal advance."""
        tech = raw_state.get(_TECH_STATE_KEY, {})

        # Loom at 12+ vils
        loom_info = tech.get(str(Technology.LOOM), {})
        loom_done = loom_info.get("researched", False)
        if (
            not loom_done
            and w.villager_count >= 12
            and w.can_afford(food=50)
            and w.commands.can_issue("RESEARCH", "loom")
            and not w.queue.has_active("research_loom")
        ):
            w.queue.add_action(self._make_research_action(
                "research_loom", w, Priority.NORMAL, lambda: self.ctrl.research_loom(),
            ))

        # Farms when food is low and berries are depleted
        self._build_farms(w)

        # Advance to Feudal
        if (
            w.can_afford(food=500)
            and w.commands.can_issue("RESEARCH", "feudal")
            and not w.queue.has_active("advance_feudal")
        ):
            w.queue.add_action(self._make_research_action(
                "advance_feudal", w, Priority.URGENT, lambda: self.ctrl.advance_to_feudal(),
            ))

    # ================================================================
    # Phase 3: Feudal Age
    # ================================================================

    def _phase_3_feudal(self, w: WorldState, raw_state: dict) -> None:
        """Blacksmith + market (Castle prereqs), eco upgrades, gold collection."""
        # Blacksmith
        if (
            not w.has_building("BLACKSMITH", complete_only=False)
            and w.can_afford(wood=150)
            and w.commands.can_issue("BUILD", "BLACKSMITH")
            and not w.queue.has_active("build_blacksmith")
        ):
            w.queue.add_action(self._make_build_action(
                "build_blacksmith", "BLACKSMITH", w, Priority.HIGH,
            ))

        # Market
        if (
            not w.has_building("MARKET", complete_only=False)
            and w.can_afford(wood=175)
            and w.commands.can_issue("BUILD", "MARKET")
            and not w.queue.has_active("build_market")
        ):
            w.queue.add_action(self._make_build_action(
                "build_market", "MARKET", w, Priority.HIGH,
            ))

        # Eco upgrades
        tech = raw_state.get(_TECH_STATE_KEY, {})

        dba_done = tech.get(str(Technology.DOUBLE_BIT_AXE), {}).get("researched", False)
        if (
            not dba_done
            and w.has_building("LUMBER_CAMP")
            and w.commands.can_issue("RESEARCH", "double_bit_axe")
            and not w.queue.has_active("research_double_bit_axe")
        ):
            w.queue.add_action(self._make_research_action(
                "research_double_bit_axe", w, Priority.NORMAL,
                lambda: self.ctrl.research(Technology.DOUBLE_BIT_AXE),
            ))

        hc_done = tech.get(str(Technology.HORSE_COLLAR), {}).get("researched", False)
        if (
            not hc_done
            and w.has_building("MILL")
            and w.commands.can_issue("RESEARCH", "horse_collar")
            and not w.queue.has_active("research_horse_collar")
        ):
            w.queue.add_action(self._make_research_action(
                "research_horse_collar", w, Priority.LOW,
                lambda: self.ctrl.research(Technology.HORSE_COLLAR),
            ))

        # Mining camp near gold if we have no gold drop-off
        # (eco manager handles this via DropoffNeeded, but ensure gold
        # collection is happening for Castle Age advance)

        # Farms
        self._build_farms(w)

        # Advance to Castle
        if (
            w.can_afford(food=800, gold=200)
            and w.has_building("BLACKSMITH")
            and w.has_building("MARKET")
            and w.commands.can_issue("RESEARCH", "castle")
            and not w.queue.has_active("advance_castle")
        ):
            w.queue.add_action(self._make_research_action(
                "advance_castle", w, Priority.URGENT, lambda: self.ctrl.advance_to_castle(),
            ))

    # ================================================================
    # Phase 4: Castle Age Boom
    # ================================================================

    def _phase_4_castle_boom(self, w: WorldState, raw_state: dict) -> None:
        """Extra TCs, mass farms, eco upgrades, start military."""
        # 2nd TC
        if (
            w.building_count("TOWN_CENTER") < 2
            and w.can_afford(wood=275, stone=100)
            and w.commands.can_issue("BUILD", "build_2nd_tc")
            and not w.queue.has_active("build_2nd_tc")
        ):
            ctrl = self.ctrl

            def build_2nd_tc() -> dict:
                pos = w.spatial.find_placement("TOWN_CENTER", goal=PlacementGoal.NEAR_TC)
                if pos is None:
                    pos_fallback = w.spatial.layout.base_center.offset(10, 0)
                else:
                    pos_fallback = pos
                resp = ctrl.place_building("TOWN_CENTER", pos_fallback.x, pos_fallback.y)
                if resp.get("action") == "error":
                    logger.warning("2nd TC build failed: %s", resp.get("error"))
                    return resp
                w.commands.issue(
                    "BUILD", target_position=pos_fallback, building_type="TOWN_CENTER",
                    game_time=w.game_time, key="build_2nd_tc",
                )
                return resp

            w.queue.add_action(QueuedAction(
                name="build_2nd_tc", priority=Priority.HIGH, execute=build_2nd_tc,
            ))

        # 3rd TC
        if (
            w.building_count("TOWN_CENTER") == 2
            and w.villager_count >= 25
            and w.can_afford(wood=275, stone=100)
            and w.commands.can_issue("BUILD", "build_3rd_tc")
            and not w.queue.has_active("build_3rd_tc")
        ):
            ctrl = self.ctrl

            def build_3rd_tc() -> dict:
                pos = w.spatial.find_placement("TOWN_CENTER", goal=PlacementGoal.NEAR_TC)
                if pos is None:
                    pos_fallback = w.spatial.layout.base_center.offset(-10, 0)
                else:
                    pos_fallback = pos
                resp = ctrl.place_building("TOWN_CENTER", pos_fallback.x, pos_fallback.y)
                if resp.get("action") == "error":
                    logger.warning("3rd TC build failed: %s", resp.get("error"))
                    return resp
                w.commands.issue(
                    "BUILD", target_position=pos_fallback, building_type="TOWN_CENTER",
                    game_time=w.game_time, key="build_3rd_tc",
                )
                return resp

            w.queue.add_action(QueuedAction(
                name="build_3rd_tc", priority=Priority.HIGH, execute=build_3rd_tc,
            ))

        # Barracks
        if (
            not w.has_building("BARRACKS", complete_only=False)
            and w.can_afford(wood=175)
            and w.commands.can_issue("BUILD", "BARRACKS")
            and not w.queue.has_active("build_barracks")
        ):
            w.queue.add_action(self._make_build_action(
                "build_barracks", "BARRACKS", w, Priority.NORMAL,
            ))

        # Stable (requires barracks)
        if (
            not w.has_building("STABLE", complete_only=False)
            and w.has_building("BARRACKS")
            and w.can_afford(wood=175)
            and w.commands.can_issue("BUILD", "STABLE")
            and not w.queue.has_active("build_stable")
        ):
            w.queue.add_action(self._make_build_action(
                "build_stable", "STABLE", w, Priority.NORMAL,
            ))

        # Train knights
        if (
            w.has_building("STABLE")
            and w.villager_count >= 25
            and w.can_afford(food=120, gold=75)
            and w.commands.can_issue("TRAIN", "knight")
            and not w.queue.has_active("train_knight")
        ):
            w.queue.add_action(self._make_train_action(
                "train_knight", w, Priority.NORMAL, lambda: self.ctrl.train_knight(),
            ))

        # Farms
        self._build_farms(w)

        # Eco upgrades
        tech = raw_state.get(_TECH_STATE_KEY, {})

        wb_done = tech.get(str(Technology.WHEELBARROW), {}).get("researched", False)
        if (
            not wb_done
            and w.commands.can_issue("RESEARCH", "wheelbarrow")
            and not w.queue.has_active("research_wheelbarrow")
        ):
            w.queue.add_action(self._make_research_action(
                "research_wheelbarrow", w, Priority.LOW,
                lambda: self.ctrl.research(Technology.WHEELBARROW),
            ))

        bs_done = tech.get(str(Technology.BOW_SAW), {}).get("researched", False)
        if (
            not bs_done
            and w.has_building("LUMBER_CAMP")
            and w.commands.can_issue("RESEARCH", "bow_saw")
            and not w.queue.has_active("research_bow_saw")
        ):
            w.queue.add_action(self._make_research_action(
                "research_bow_saw", w, Priority.LOW,
                lambda: self.ctrl.research(Technology.BOW_SAW),
            ))

        gm_done = tech.get(str(Technology.GOLD_MINING), {}).get("researched", False)
        if (
            not gm_done
            and w.commands.can_issue("RESEARCH", "gold_mining")
            and not w.queue.has_active("research_gold_mining")
        ):
            w.queue.add_action(self._make_research_action(
                "research_gold_mining", w, Priority.LOW,
                lambda: self.ctrl.research(Technology.GOLD_MINING),
            ))

    # ================================================================
    # Farm building (shared across phases 2-4)
    # ================================================================

    def _build_farms(self, w: WorldState) -> None:
        """Build farms when food is low. Error-checked placement."""
        if not w.can_afford(wood=60):
            return
        if not w.commands.can_issue("BUILD", "FARM"):
            return
        # Farms require a food drop-off -- mill or completed TC
        if not (w.has_building("MILL", complete_only=False) or w.tc_is_complete()):
            return

        # Count existing + in-progress farms
        farm_count = w.building_count("FARM")
        food_vils_needed = max(0, w.villager_count // 3 - farm_count)

        idle_count = len(w.idle_vils())
        if w.food < 50:
            prio = Priority.URGENT
        elif w.food < 200 and (idle_count >= 2 or food_vils_needed > 0):
            prio = Priority.HIGH
        elif w.food < 300 and w.villager_count >= 10:
            prio = Priority.NORMAL
        else:
            return

        # Queue multiple farms when starving, but don't spam at normal priority
        if w.queue.has_active("build_farm") and prio < Priority.URGENT:
            return

        logger.info("Queuing farm (prio=%d, farms=%d, food=%.0f)", prio, farm_count, w.food)
        ctrl = self.ctrl
        spatial = w.spatial

        def build_farm() -> dict:
            center = spatial.layout.tc_pos or spatial.layout.base_center
            pos = spatial.find_placement("FARM", goal=PlacementGoal.FARM_RING, near=center)
            if pos is None:
                pos = center.offset(3, 3)

            resp = ctrl.place_building("FARM", pos.x, pos.y)
            if resp.get("action") == "error":
                logger.warning("Farm build failed: %s", resp.get("error"))
                return resp
            w.commands.issue(
                "BUILD", target_position=pos, building_type="FARM",
                game_time=w.game_time, key="FARM",
            )
            return resp

        w.queue.add_action(QueuedAction(
            name="build_farm", priority=prio, execute=build_farm,
        ))
