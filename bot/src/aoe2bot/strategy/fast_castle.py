"""Fast Castle strategy -- WorldState + EventQueue foundation.

Every decision reads from WorldState. Every command goes through EventQueue.
No direct ctrl.* calls for game commands -- only QueuedActions executed by the queue.
"""

from __future__ import annotations

import math
import logging
from typing import TYPE_CHECKING

from ..protocol import Technology
from .actions import Priority
from .base import BaseStrategy
from .eco import EcoManager
from .event_queue import ActionSequence, QueuedAction, WaitCondition
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
    """Adaptive Fast Castle -- works from any game state toward Castle Age boom.

    All state queries go through WorldState.
    All commands go through EventQueue as QueuedActions / ActionSequences.
    The runner calls world.queue.tick() AFTER on_tick to execute one command.

    Priority tiers:
      CRITICAL(100): Build TC if none, build house if pop-blocked
      URGENT(80):    Train villager, advance age
      HIGH(60):      Scout base, assign idle vils, key eco buildings
      NORMAL(40):    Research, military buildings
      LOW(20):       Extra houses, eco techs
    """

    TARGET_VIL_POP = 40
    COMPLETE_POP = 50

    def __init__(self, ctrl: GameController):
        super().__init__(ctrl)
        self.eco = EcoManager()
        self._tick_count = 0
        self._last_logged_action: str | None = None
        self._last_raw: dict = {}

    @property
    def name(self) -> str:
        return "fast-castle"

    def on_start(self) -> None:
        self.running = True
        logger.info("FastCastle strategy started (WorldState + EventQueue)")

    def on_tick(self, raw_state: dict, world: WorldState | None = None) -> str | None:
        if world is None:
            return None

        self._last_raw = raw_state
        self._tick_count += 1
        w = world

        # -- CRITICAL --
        self._eval_tc(w)
        self._eval_housing(w)

        # -- URGENT --
        self._eval_train_villager(w)

        # -- HIGH --
        self._eval_idle_vils(w, raw_state)

        # -- Age-specific goals --
        if w.age == 0:
            self._dark_age(w, raw_state)
        elif w.age == 1:
            self._feudal_age(w, raw_state)
        elif w.age >= 2:
            self._castle_age(w, raw_state)

        # -- Scouting --
        self._eval_scouting(w)

        # Log the current state and what's queued
        queued_name = self._log_tick(w)
        return queued_name

    def is_complete(self, raw_state: dict) -> bool:
        age = raw_state.get("age", 0)
        vil_count = raw_state.get("villagerCount", 0)
        pop = raw_state.get("population", {}).get("current", 0)
        return age >= 2 and vil_count >= 35 and pop >= self.COMPLETE_POP

    # ================================================================
    # Logging
    # ================================================================

    def _log_tick(self, w: WorldState) -> str | None:
        """Log one line per tick: state + what was queued."""
        # Summarize what's in the queue
        sequences = w.queue.get_active_sequences()
        standalone_names: list[str] = []

        # Peek at standalone actions (they're sorted by priority in tick())
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

        if queued_desc and queued_desc != self._last_logged_action:
            logger.info(
                "[%d:%02d] %s | Pop %d/%d | F:%.0f W:%.0f G:%.0f S:%.0f | Idle:%d | -> %s",
                m, s,
                age_name,
                w.population, pop_cap,
                w.food, w.wood, w.gold, w.stone,
                idle_count,
                queued_desc,
            )
            self._last_logged_action = queued_desc
        elif self._tick_count % 10 == 0:
            logger.info(
                "[%d:%02d] %s | Pop %d/%d | F:%.0f W:%.0f G:%.0f S:%.0f | Idle:%d",
                m, s,
                age_name,
                w.population, pop_cap,
                w.food, w.wood, w.gold, w.stone,
                idle_count,
            )
        return queued_desc

    # ================================================================
    # Placement helper -- builds a QueuedAction that places via spatial
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
        """Create a QueuedAction that finds a spot via spatial and places a building."""
        ctrl = self.ctrl
        place_name = building_name_override or building

        def execute() -> dict:
            pos = w.spatial.find_placement(building, goal=goal, near=near)
            if pos is None:
                resp = ctrl.smart_build(place_name, padding=0)
            else:
                resp = ctrl.place_building(place_name, pos.x, pos.y)
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
            w.commands.issue("RESEARCH", game_time=w.game_time, key=name)
            return resp

        return QueuedAction(name=name, priority=priority, execute=execute)

    # ================================================================
    # CRITICAL evaluators
    # ================================================================

    def _eval_tc(self, w: WorldState) -> None:
        """Build TC if we have none and none is in progress."""
        has_tc = w.has_building("TOWN_CENTER", complete_only=False)
        if has_tc:
            return
        if not w.commands.can_issue("BUILD", "build_tc"):
            return
        if not w.can_afford(wood=275, stone=100):
            return
        if w.queue.has_active("build_tc"):
            return

        ctrl = self.ctrl
        pos = w.spatial.find_placement("TOWN_CENTER", goal=PlacementGoal.NEAR_TC)
        if pos is None:
            pos = w.spatial.layout.base_center

        def build_tc(p=pos) -> dict:
            resp = ctrl.place_building("TOWN_CENTER_FOUNDATION", p.x, p.y)
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
    # URGENT evaluators
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
    # HIGH evaluators
    # ================================================================

    def _eval_idle_vils(self, w: WorldState, raw_state: dict) -> None:
        """Assign idle vils to the most-needed resource."""
        idle = w.idle_vils()
        if not idle:
            return
        if w.queue.has_active("assign_vils"):
            return

        assignment = self.eco.get_idle_assignment_world(w, raw_state)
        if assignment is None:
            return

        ctrl = self.ctrl
        vil_ids = assignment.vil_ids
        target_id = assignment.target_id
        resource = assignment.resource

        def execute() -> dict:
            resp = ctrl.attack_target(vil_ids, target_id)
            w.commands.issue(
                "GATHER", unit_ids=vil_ids, target_id=target_id,
                game_time=w.game_time, key=f"gather_{resource}",
            )
            return resp

        w.queue.add_action(QueuedAction(
            name=f"assign_vils_{resource}",
            priority=Priority.HIGH,
            execute=execute,
        ))

    # ================================================================
    # Dark Age
    # ================================================================

    def _dark_age(self, w: WorldState, raw_state: dict) -> None:
        # Lumber camp near trees (sequence: place + wait for foundation)
        if (
            not w.has_building("LUMBER_CAMP", complete_only=False)
            and w.commands.can_issue("BUILD", "LUMBER_CAMP")
            and not w.queue.has_active("setup_wood")
            and w.can_afford(wood=100)
            and w.villager_count >= 6
        ):
            self._queue_lumber_camp_sequence(w)

        # Mill near berries (sequence: place mill, wait, then farms)
        if (
            not w.has_building("MILL", complete_only=False)
            and w.commands.can_issue("BUILD", "MILL")
            and not w.queue.has_active("setup_food")
            and w.can_afford(wood=100)
            and w.villager_count >= 6
        ):
            self._queue_food_eco_sequence(w)

        # Loom
        tech = raw_state.get(_TECH_STATE_KEY, {})
        loom_info = tech.get(str(Technology.LOOM), {})
        loom_done = loom_info.get("researched", False)
        if (
            not loom_done
            and w.can_afford(food=50)
            and w.villager_count >= 12
            and w.commands.can_issue("RESEARCH", "loom")
            and not w.queue.has_active("research_loom")
        ):
            w.queue.add_action(self._make_research_action(
                "research_loom", w, Priority.NORMAL, lambda: self.ctrl.research_loom(),
            ))

        # Farms when food is low
        self._eval_farms(w)

        # Advance to Feudal
        if (
            w.age == 0
            and w.can_afford(food=500)
            and w.commands.can_issue("RESEARCH", "feudal")
            and not w.queue.has_active("advance_feudal")
        ):
            w.queue.add_action(self._make_research_action(
                "advance_feudal", w, Priority.URGENT, lambda: self.ctrl.advance_to_feudal(),
            ))

    # ================================================================
    # Feudal Age
    # ================================================================

    def _feudal_age(self, w: WorldState, raw_state: dict) -> None:
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

        # Advance to Castle
        if (
            w.age == 1
            and w.can_afford(food=800, gold=200)
            and w.has_building("BLACKSMITH")
            and w.has_building("MARKET")
            and w.commands.can_issue("RESEARCH", "castle")
            and not w.queue.has_active("advance_castle")
        ):
            w.queue.add_action(self._make_research_action(
                "advance_castle", w, Priority.URGENT, lambda: self.ctrl.advance_to_castle(),
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

        # Farms
        self._eval_farms(w)

    # ================================================================
    # Castle Age+
    # ================================================================

    def _castle_age(self, w: WorldState, raw_state: dict) -> None:
        # Second TC
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
                    pos = w.spatial.layout.base_center.offset(10, 0)
                resp = ctrl.place_building("TOWN_CENTER_FOUNDATION", pos.x, pos.y)
                w.commands.issue(
                    "BUILD", target_position=pos, building_type="TOWN_CENTER",
                    game_time=w.game_time, key="build_2nd_tc",
                )
                return resp

            w.queue.add_action(QueuedAction(
                name="build_2nd_tc", priority=Priority.HIGH, execute=build_2nd_tc,
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
        self._eval_farms(w)

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
    # Multi-step sequences
    # ================================================================

    def _queue_lumber_camp_sequence(self, w: WorldState) -> None:
        """Place lumber camp near trees, then wait for foundation to appear."""
        ctrl = self.ctrl
        spatial = w.spatial

        def build_lumber_camp() -> dict:
            pos = spatial.find_lumber_camp_spot()
            if pos is None:
                resp = ctrl.smart_build("LUMBER_CAMP", padding=0)
            else:
                resp = ctrl.place_building("LUMBER_CAMP", pos.x, pos.y)
            w.commands.issue(
                "BUILD", target_position=pos, building_type="LUMBER_CAMP",
                game_time=w.game_time, key="LUMBER_CAMP",
            )
            return resp

        w.queue.add_sequence(ActionSequence(
            name="setup_wood_eco",
            priority=Priority.HIGH,
            steps=[
                QueuedAction(
                    name="place_lumber_camp",
                    priority=Priority.HIGH,
                    execute=build_lumber_camp,
                ),
                WaitCondition(
                    name="wait_lumber_camp_foundation",
                    check=lambda: w.has_building("LUMBER_CAMP", complete_only=False),
                    timeout=20.0,
                    on_timeout="skip",
                ),
            ],
        ))

    def _queue_food_eco_sequence(self, w: WorldState) -> None:
        """Place mill near berries, wait for it, then queue farms around it."""
        ctrl = self.ctrl
        spatial = w.spatial

        def build_mill() -> dict:
            pos = spatial.find_mill_spot()
            if pos is None:
                resp = ctrl.smart_build("MILL", padding=0)
            else:
                resp = ctrl.place_building("MILL", pos.x, pos.y)
            w.commands.issue(
                "BUILD", target_position=pos, building_type="MILL",
                game_time=w.game_time, key="MILL",
            )
            return resp

        def build_farm_near_mill() -> dict:
            mill = w.buildings.get_nearest("MILL", w.spatial.layout.base_center)
            center = mill.position if mill else w.spatial.layout.base_center
            pos = spatial.find_placement("FARM", goal=PlacementGoal.FARM_RING, near=center)
            if pos is None:
                pos = center.offset(3, 0)
            resp = ctrl.place_building("FARM", pos.x, pos.y)
            w.commands.issue(
                "BUILD", target_position=pos, building_type="FARM",
                game_time=w.game_time, key=f"FARM_{pos}",
            )
            return resp

        w.queue.add_sequence(ActionSequence(
            name="setup_food_eco",
            priority=Priority.HIGH,
            steps=[
                QueuedAction(
                    name="place_mill",
                    priority=Priority.HIGH,
                    execute=build_mill,
                ),
                WaitCondition(
                    name="wait_mill_foundation",
                    check=lambda: w.has_building("MILL", complete_only=False),
                    timeout=20.0,
                    on_timeout="skip",
                ),
                WaitCondition(
                    name="wait_mill_complete",
                    check=lambda: w.has_building("MILL", complete_only=True),
                    timeout=90.0,
                    on_timeout="skip",  # start farms even if mill isn't done
                ),
                QueuedAction(
                    name="place_farm_1",
                    priority=Priority.HIGH,
                    execute=build_farm_near_mill,
                    condition=lambda: w.can_afford(wood=60),
                ),
                QueuedAction(
                    name="place_farm_2",
                    priority=Priority.HIGH,
                    execute=build_farm_near_mill,
                    condition=lambda: w.can_afford(wood=60),
                ),
                QueuedAction(
                    name="place_farm_3",
                    priority=Priority.HIGH,
                    execute=build_farm_near_mill,
                    condition=lambda: w.can_afford(wood=60),
                ),
            ],
        ))

    def _eval_farms(self, w: WorldState) -> None:
        """Build farms via spatial engine when food is low."""
        if not w.can_afford(wood=60):
            return
        if w.queue.has_active("build_farm"):
            return
        # Farms require a mill — don't attempt without one
        if not w.has_building("MILL", complete_only=False):
            return

        idle_count = len(w.idle_vils())
        if w.food < 50:
            prio = Priority.URGENT
        elif w.food < 200 and idle_count >= 2:
            prio = Priority.HIGH
        elif w.food < 300 and w.villager_count >= 10:
            prio = Priority.NORMAL
        else:
            return

        ctrl = self.ctrl
        spatial = w.spatial
        farm_id = f"FARM_{self._tick_count}"

        def build_farm() -> dict:
            center = spatial.layout.tc_pos or spatial.layout.base_center
            pos = spatial.find_placement("FARM", goal=PlacementGoal.FARM_RING, near=center)
            if pos is None:
                pos = center.offset(3, 3)
            resp = ctrl.place_building("FARM", pos.x, pos.y)
            w.commands.issue(
                "BUILD", target_position=pos, building_type="FARM",
                game_time=w.game_time, key=farm_id,
            )
            return resp

        w.queue.add_action(QueuedAction(
            name="build_farm", priority=prio, execute=build_farm,
        ))

    # ================================================================
    # Scouting -- ActionSequence with waypoints and wait conditions
    # ================================================================

    def _eval_scouting(self, w: WorldState) -> None:
        """Scout around base using an expanding circle sequence."""
        if w.queue.has_active("scout_base"):
            return

        # Only queue once during the first ~10 ticks
        if self._tick_count > 10:
            return

        base = w.spatial.layout.base_center
        ctrl = self.ctrl

        # Find scout unit (class 961)
        scout_id: int | None = None
        for u in w.units.get_all():
            if u.is_scout:
                scout_id = u.id
                break

        if scout_id is None:
            return

        # Generate waypoints in expanding circles, biased toward unexplored
        steps: list[QueuedAction | WaitCondition] = []
        sid = scout_id

        for radius in (15, 25, 35):
            # Check for the most unexplored direction first
            unexplored_dir = w.map.get_unexplored_direction(base)
            if unexplored_dir is not None:
                start_angle = math.atan2(unexplored_dir.y, unexplored_dir.x)
            else:
                start_angle = 0.0

            for i in range(8):
                angle = start_angle + (i * math.pi / 4)
                tx = base.x + radius * math.cos(angle)
                ty = base.y + radius * math.sin(angle)
                target = Position(tx, ty)

                def make_move(t=target, s=sid):
                    def execute() -> dict:
                        resp = ctrl.move_units([s], t.x, t.y)
                        w.commands.issue(
                            "MOVE", unit_ids=[s], target_position=t,
                            game_time=w.game_time, key=f"scout_{t}",
                        )
                        return resp
                    return execute

                steps.append(QueuedAction(
                    name=f"scout_move_{target}",
                    priority=Priority.HIGH,
                    execute=make_move(),
                ))

                def make_check(t=target, s=sid):
                    def check() -> bool:
                        unit = w.units.get_unit(s)
                        if unit is None:
                            return True  # scout died, skip
                        return unit.position.distance_to(t) <= 5.0
                    return check

                steps.append(WaitCondition(
                    name=f"wait_scout_near_{target}",
                    check=make_check(),
                    timeout=15.0,
                    on_timeout="skip",
                ))

        if steps:
            w.queue.add_sequence(ActionSequence(
                name="scout_base",
                priority=Priority.HIGH,
                steps=steps,
            ))
