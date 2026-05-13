"""High-level game controller that Claude uses to play AoE2."""

from __future__ import annotations

import json
import logging
from typing import Any

from .client import AoE2Client, TcpClient
from .game_state import GameState, Unit, Building, MapTile, Player, Resources
from .protocol import (
    cmd_ping, cmd_get_state, cmd_get_resources, cmd_get_units,
    cmd_get_buildings, cmd_get_map, cmd_get_map_tiles, cmd_get_players,
    cmd_get_tech_state, cmd_train, cmd_build, cmd_research, cmd_move,
    cmd_attack, cmd_attack_move, cmd_patrol, cmd_garrison, cmd_set_stance,
    cmd_scout, cmd_set_camera, cmd_chat, cmd_can_afford, cmd_find_path,
    cmd_pause, cmd_unpause, cmd_set_speed, cmd_resign, cmd_set_gather_point,
    cmd_smart_build, cmd_find_placement, cmd_queue_build, cmd_get_town_centers,
    cmd_get_building_counts, cmd_set_vil_priorities,
    cmd_place_building, cmd_reload_module,
    UnitType, BuildingType, Technology, CombatStance, Age,
)

logger = logging.getLogger(__name__)


class GameController:
    """
    High-level interface for controlling an AoE2:DE game.

    Usage:
        ctrl = GameController()
        ctrl.connect()
        state = ctrl.get_state()
        print(state.summary())
        ctrl.train_villager()
        ctrl.disconnect()
    """

    def __init__(
        self,
        pipe_name: str | None = None,
        target_player: int | None = None,
        client: AoE2Client | TcpClient | None = None,
        tcp_host: str | None = None,
        tcp_port: int | None = None,
    ):
        if client is not None:
            self.client = client
        elif tcp_host or tcp_port:
            self.client = TcpClient(
                host=tcp_host or "127.0.0.1",
                port=tcp_port or 9999,
                target_player=target_player,
            )
        else:
            kwargs: dict = {}
            if pipe_name:
                kwargs["pipe_name"] = pipe_name
            if target_player is not None:
                kwargs["target_player"] = target_player
            self.client = AoE2Client(**kwargs)
        self._last_state: GameState | None = None

    def connect(self, timeout_ms: int = 10000) -> str:
        self.client.connect(timeout_ms)
        resp = self.client.request(cmd_ping())
        return f"Connected! Player {resp.get('playerId')} | Game time: {resp.get('time', 0):.1f}s"

    def disconnect(self) -> None:
        self.client.disconnect()

    @property
    def connected(self) -> bool:
        return self.client.connected

    # ── State Reading ─────────────────────────────────────────────────────

    def get_state(self) -> GameState:
        resp = self.client.request(cmd_get_state())
        self._last_state = GameState.from_dict(resp)
        return self._last_state

    def get_resources(self) -> Resources:
        resp = self.client.request(cmd_get_resources())
        return Resources.from_dict(resp.get("resources", {}))

    def get_units(self, unit_type: int | None = None) -> list[Unit]:
        resp = self.client.request(cmd_get_units(unit_type=unit_type))
        return [Unit.from_dict(u) for u in resp.get("units", [])]

    def get_idle_villagers(self) -> list[Unit]:
        units = self.get_units(unit_type=UnitType.VILLAGER)
        return [u for u in units if u.idle]

    def get_military(self) -> list[Unit]:
        all_units = self.get_units()
        military_threshold = 900
        return [u for u in all_units if u.type != UnitType.VILLAGER and u.type < military_threshold]

    def get_buildings(self) -> list[Building]:
        resp = self.client.request(cmd_get_buildings())
        return [Building.from_dict(b) for b in resp.get("buildings", [])]

    def get_map_info(self) -> dict:
        return self.client.request(cmd_get_map())

    def get_map_tiles(self, x1: int = 0, y1: int = 0, x2: int = 50, y2: int = 50) -> list[MapTile]:
        resp = self.client.request(cmd_get_map_tiles(x1, y1, x2, y2))
        return [MapTile.from_dict(t) for t in resp.get("tiles", [])]

    def get_players(self) -> list[Player]:
        resp = self.client.request(cmd_get_players())
        return [Player.from_dict(p) for p in resp.get("players", [])]

    def get_enemies(self) -> list[Player]:
        return [p for p in self.get_players() if p.is_enemy]

    def can_afford(self, unit_type: int, is_building: bool = False) -> dict:
        return self.client.request(cmd_can_afford(unit_type, is_building))

    def get_tech_state(self, technologies: list[int]) -> dict:
        return self.client.request(cmd_get_tech_state(technologies))

    # ── Unit Production ───────────────────────────────────────────────────

    def train(self, unit_type: int, amount: int = 1) -> dict:
        return self.client.request(cmd_train(unit_type, amount))

    def train_villager(self, amount: int = 1) -> dict:
        return self.train(UnitType.VILLAGER, amount)

    def train_militia(self, amount: int = 1) -> dict:
        return self.train(UnitType.MILITIA, amount)

    def train_archer(self, amount: int = 1) -> dict:
        return self.train(UnitType.ARCHER, amount)

    def train_skirmisher(self, amount: int = 1) -> dict:
        return self.train(UnitType.SKIRMISHER, amount)

    def train_spearman(self, amount: int = 1) -> dict:
        return self.train(UnitType.SPEARMAN, amount)

    def train_scout(self, amount: int = 1) -> dict:
        return self.train(UnitType.SCOUT_CAVALRY, amount)

    def train_knight(self, amount: int = 1) -> dict:
        return self.train(UnitType.KNIGHT, amount)

    def train_monk(self, amount: int = 1) -> dict:
        return self.train(UnitType.MONK, amount)

    # ── Building ──────────────────────────────────────────────────────────

    def build(self, building_type: int, x: float, y: float, builder_ids: list[int] | None = None) -> dict:
        return self.client.request(cmd_build(building_type, x, y, builder_ids))

    def build_house(self, x: float, y: float) -> dict:
        return self.build(BuildingType.HOUSE, x, y)

    def build_barracks(self, x: float, y: float) -> dict:
        return self.build(BuildingType.BARRACKS, x, y)

    def build_lumber_camp(self, x: float, y: float) -> dict:
        return self.build(BuildingType.LUMBER_CAMP, x, y)

    def build_mining_camp(self, x: float, y: float) -> dict:
        return self.build(BuildingType.MINING_CAMP, x, y)

    def build_mill(self, x: float, y: float) -> dict:
        return self.build(BuildingType.MILL, x, y)

    def build_farm(self, x: float, y: float) -> dict:
        return self.build(BuildingType.FARM, x, y)

    def build_archery_range(self, x: float, y: float) -> dict:
        return self.build(BuildingType.ARCHERY_RANGE, x, y)

    def build_stable(self, x: float, y: float) -> dict:
        return self.build(BuildingType.STABLE, x, y)

    def build_blacksmith(self, x: float, y: float) -> dict:
        return self.build(BuildingType.BLACKSMITH, x, y)

    def build_market(self, x: float, y: float) -> dict:
        return self.build(BuildingType.MARKET, x, y)

    def build_town_center(self, x: float, y: float) -> dict:
        return self.build(BuildingType.TOWN_CENTER, x, y)

    def build_castle(self, x: float, y: float) -> dict:
        return self.build(BuildingType.CASTLE, x, y)

    # ── Research ──────────────────────────────────────────────────────────

    def research(self, technology: int) -> dict:
        return self.client.request(cmd_research(technology))

    def research_loom(self) -> dict:
        return self.research(Technology.LOOM)

    def advance_to_feudal(self) -> dict:
        return self.research(Technology.FEUDAL_AGE)

    def advance_to_castle(self) -> dict:
        return self.research(Technology.CASTLE_AGE)

    def advance_to_imperial(self) -> dict:
        return self.research(Technology.IMPERIAL_AGE)

    # ── Unit Commands ─────────────────────────────────────────────────────

    def move_units(self, unit_ids: list[int], x: float, y: float) -> dict:
        return self.client.request(cmd_move(unit_ids, x, y))

    def attack_target(self, unit_ids: list[int], target_id: int) -> dict:
        return self.client.request(cmd_attack(unit_ids, target_id))

    def attack_move(self, unit_ids: list[int], x: float, y: float) -> dict:
        return self.client.request(cmd_attack_move(unit_ids, x, y))

    def patrol_units(self, unit_ids: list[int], x: float, y: float) -> dict:
        return self.client.request(cmd_patrol(unit_ids, x, y))

    def garrison(self, unit_ids: list[int], building_id: int) -> dict:
        return self.client.request(cmd_garrison(unit_ids, building_id))

    def set_stance(self, unit_ids: list[int], stance: int) -> dict:
        return self.client.request(cmd_set_stance(unit_ids, stance))

    def set_aggressive(self, unit_ids: list[int]) -> dict:
        return self.set_stance(unit_ids, CombatStance.AGGRESSIVE)

    def set_defensive(self, unit_ids: list[int]) -> dict:
        return self.set_stance(unit_ids, CombatStance.DEFENSIVE)

    def set_stand_ground(self, unit_ids: list[int]) -> dict:
        return self.set_stance(unit_ids, CombatStance.STAND_GROUND)

    def auto_scout(self) -> dict:
        return self.client.request(cmd_scout())

    def set_gather_point(self, building_ids: list[int], x: float, y: float) -> dict:
        return self.client.request(cmd_set_gather_point(building_ids, x, y))

    # ── Game Control ──────────────────────────────────────────────────────

    def pause(self) -> dict:
        return self.client.request(cmd_pause())

    def unpause(self) -> dict:
        return self.client.request(cmd_unpause())

    def set_speed(self, speed: float) -> dict:
        return self.client.request(cmd_set_speed(speed))

    def set_camera(self, x: float, y: float) -> dict:
        return self.client.request(cmd_set_camera(x, y))

    def chat(self, message: str) -> dict:
        return self.client.request(cmd_chat(message))

    def find_path(self, x1: float, y1: float, x2: float, y2: float) -> list[dict]:
        resp = self.client.request(cmd_find_path(x1, y1, x2, y2))
        return resp.get("path", [])

    def resign(self) -> dict:
        return self.client.request(cmd_resign())

    # ── Smart Building (uses ConstructionPlacement) ─────────────────────

    def smart_build(self, building_name: str, x: float | None = None, y: float | None = None, padding: int = 1) -> dict:
        return self.client.request(cmd_smart_build(building_name, x, y, padding))

    def smart_build_house(self) -> dict:
        return self.smart_build("HOUSE")

    def smart_build_farm(self) -> dict:
        return self.smart_build("FARM")

    def smart_build_lumber_camp(self) -> dict:
        return self.smart_build("LUMBER_CAMP")

    def smart_build_mining_camp(self) -> dict:
        return self.smart_build("MINING_CAMP")

    def smart_build_mill(self) -> dict:
        return self.smart_build("MILL")

    def smart_build_barracks(self, x: float | None = None, y: float | None = None) -> dict:
        return self.smart_build("BARRACKS", x, y)

    def find_placement(self, building_name: str, x: float | None = None, y: float | None = None, padding: int = 1) -> dict:
        return self.client.request(cmd_find_placement(building_name, x, y, padding))

    def queue_build(self, building_name: str, priority: int = 5, padding: int = 1) -> dict:
        return self.client.request(cmd_queue_build(building_name, priority, padding))

    def get_town_centers(self) -> list[dict]:
        resp = self.client.request(cmd_get_town_centers())
        return resp.get("tcs", [])

    def get_building_counts(self) -> dict[str, int]:
        resp = self.client.request(cmd_get_building_counts())
        return resp.get("counts", {})

    def set_vil_priorities(self, wood: int, food: int, gold: int, stone: int) -> dict:
        return self.client.request(cmd_set_vil_priorities(wood, food, gold, stone))

    def place_building(self, building_name: str, x: float, y: float) -> dict:
        return self.client.request(cmd_place_building(building_name, x, y))

    def reload_module(self) -> dict:
        return self.client.request(cmd_reload_module())

    # ── Convenience ───────────────────────────────────────────────────────

    @property
    def last_state(self) -> GameState | None:
        return self._last_state

    def status(self) -> str:
        """Get a quick human-readable status string."""
        state = self.get_state()
        return state.summary()
