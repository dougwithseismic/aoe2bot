"""Strategy runner -- game loop that polls state and feeds strategy ticks."""

from __future__ import annotations

import logging
import sys
import time
from typing import TYPE_CHECKING

from ..protocol import cmd_get_state, cmd_get_tech_state, cmd_get_building_counts
from .world import WorldState

if TYPE_CHECKING:
    from ..controller import GameController
    from .base import BaseStrategy

logger = logging.getLogger(__name__)

# Technologies we track each enrichment cycle
TRACKED_TECHS = [22, 101, 102, 103, 202, 203, 14, 213, 55, 67, 199]

# How often (in ticks) to refresh each enrichment category
_ENRICH_INTERVAL = 5
_SCAN_AVAILABLE_INTERVAL = 20


class StrategyRunner:
    """Main game loop.

    Each tick:
    1. Poll base game state (free IPC read)
    2. Enrich with buildings / TCs / tech / resources (cached, refreshed periodically)
    3. Fetch idle villagers every tick (class 904 filter)
    4. Pass enriched state to strategy.on_tick()
    5. Sleep until next tick
    """

    def __init__(
        self,
        ctrl: GameController,
        strategy: BaseStrategy,
        tick_interval: float = 0.8,
    ):
        self.ctrl = ctrl
        self.strategy = strategy
        self.tick_interval = tick_interval
        self.tick_count = 0
        self._cache: dict = {}
        self.world = WorldState(ctrl)

    def run(self) -> None:
        _setup_logging()

        logger.info("=" * 60)
        logger.info("Strategy: %s", self.strategy.name)
        logger.info("Tick interval: %.1fs", self.tick_interval)
        logger.info("Connecting...")

        if not self.ctrl.connected:
            msg = self.ctrl.connect()
            logger.info(msg)

        self.strategy.on_start()
        logger.info("Strategy running. Press Ctrl+C to stop.")
        logger.info("=" * 60)

        try:
            self._loop()
        except KeyboardInterrupt:
            logger.info("\nStopped by user.")
        except Exception:
            logger.exception("Strategy crashed")
            raise
        finally:
            self.strategy.running = False

    def _loop(self) -> None:
        while self.strategy.running:
            tick_start = time.monotonic()

            raw_state = self._poll_state()
            if raw_state is None:
                logger.warning("Failed to get game state, retrying...")
                time.sleep(1.0)
                continue

            self.world.update(raw_state)

            if self.strategy.is_complete(raw_state):
                logger.info(
                    "Strategy complete! Age: %s, Pop: %d, Vils: %d",
                    raw_state.get("age", "?"),
                    raw_state.get("population", {}).get("current", 0),
                    raw_state.get("villagerCount", 0),
                )
                break

            self.strategy.on_tick(raw_state, self.world)
            self.tick_count += 1

            elapsed = time.monotonic() - tick_start
            sleep_time = max(0, self.tick_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _poll_state(self) -> dict | None:
        """Fetch base state and enrich with cached supplemental data."""
        try:
            raw = self.ctrl.client.request(cmd_get_state())
        except Exception as exc:
            logger.warning("State poll failed: %s", exc)
            return None

        first_tick = self.tick_count == 0

        # -- Enrichment: all categories on tick 0, then staggered --

        if first_tick or self.tick_count % _ENRICH_INTERVAL == 0:
            self._enrich_buildings()

        if first_tick or self.tick_count % _ENRICH_INTERVAL == 1:
            self._enrich_tcs()

        if first_tick or self.tick_count % _ENRICH_INTERVAL == 2:
            self._enrich_tech()

        if first_tick or self.tick_count % _ENRICH_INTERVAL == 3:
            self._enrich_resources_scan()

        if first_tick or self.tick_count % _ENRICH_INTERVAL == 4:
            self._enrich_all_units()

        if first_tick or self.tick_count % _SCAN_AVAILABLE_INTERVAL == 0:
            self._enrich_scan_available()

        if first_tick or self.tick_count % _ENRICH_INTERVAL == 2:
            self._enrich_livestock()

        # -- Idle villagers: every tick (class 904 = actual villagers) --
        self._enrich_idle_vils(raw)

        # Merge cached enrichment into raw state
        for key, value in self._cache.items():
            if key not in raw:
                raw[key] = value

        return raw

    # -- Enrichment helpers (each catches its own errors) --

    def _enrich_buildings(self) -> None:
        try:
            resp = self.ctrl.client.request(cmd_get_building_counts())
            self._cache["_buildings"] = resp.get("counts", {})
            self._cache["_building_details"] = resp.get("buildings", [])
        except Exception:
            pass

    def _enrich_tcs(self) -> None:
        try:
            resp = self.ctrl.client.request({"action": "get_town_centers"})
            self._cache["_tcs"] = resp.get("tcs", [])
        except Exception:
            pass

    def _enrich_tech(self) -> None:
        try:
            resp = self.ctrl.client.request(cmd_get_tech_state(TRACKED_TECHS))
            self._cache["_tech_state"] = resp.get("technologies", {})
        except Exception:
            pass

    def _enrich_resources_scan(self) -> None:
        try:
            resp = self.ctrl.client.request({"action": "scan_resources"})
            self._cache["_resources_scan"] = resp
        except Exception:
            pass

    def _enrich_all_units(self) -> None:
        try:
            resp = self.ctrl.client.request({"action": "get_units"})
            self._cache["_all_units"] = resp.get("units", [])
        except Exception:
            pass

    def _enrich_livestock(self) -> None:
        try:
            resp = self.ctrl.client.request({"action": "scan_livestock"})
            self._cache["_livestock"] = {
                "owned": resp.get("owned", []),
                "convertible": resp.get("convertible", []),
            }
        except Exception:
            pass

    def _enrich_scan_available(self) -> None:
        try:
            resp = self.ctrl.client.request({"action": "scan_available"})
            available: dict[str, dict] = {}
            for b in resp.get("buildings", []):
                name = b.get("name", "")
                available[name] = {
                    "available": b.get("available", False),
                    "canAfford": b.get("canAfford", False),
                    "costs": b.get("costs", []),
                }
            for u in resp.get("units", []):
                name = u.get("name", "")
                available[name] = {
                    "available": u.get("available", False),
                    "canAfford": u.get("canAfford", False),
                    "costs": u.get("costs", []),
                }
            self._cache["_available"] = available
        except Exception:
            pass

    def _enrich_idle_vils(self, raw: dict) -> None:
        """Fetch all units and filter for idle villagers (class 904 only).

        Buildings also report as idle in the game engine -- filtering by
        class 904 ensures we only count actual villager units.
        """
        try:
            resp = self.ctrl.client.request({"action": "get_units"})
            all_units = resp.get("units", [])
            vil_ids = [
                u["id"]
                for u in all_units
                if u.get("idle", False) and u.get("class") == 904
            ]
            self._cache["_idle_vil_ids"] = vil_ids
            self._cache["_all_units"] = all_units
            raw["idleVillagers"] = len(vil_ids)
        except Exception:
            self._cache.setdefault("_idle_vil_ids", [])


def _setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger("aoe2bot.strategy")
    if not root.handlers:
        root.addHandler(handler)
        root.setLevel(logging.INFO)
