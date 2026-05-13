"""Game state models — structured views of AoE2 game data."""

from __future__ import annotations

from dataclasses import dataclass, field
from .protocol import Age


@dataclass
class Resources:
    food: float = 0
    wood: float = 0
    gold: float = 0
    stone: float = 0

    def __str__(self) -> str:
        return f"F:{self.food:.0f} W:{self.wood:.0f} G:{self.gold:.0f} S:{self.stone:.0f}"

    @classmethod
    def from_dict(cls, d: dict) -> Resources:
        return cls(
            food=d.get("food", 0),
            wood=d.get("wood", 0),
            gold=d.get("gold", 0),
            stone=d.get("stone", 0),
        )


@dataclass
class Population:
    current: int = 0
    headroom: int = 0
    housing_headroom: int = 0

    @property
    def capacity(self) -> int:
        return self.current + self.headroom

    def __str__(self) -> str:
        return f"{self.current}/{self.capacity}"

    @classmethod
    def from_dict(cls, d: dict) -> Population:
        return cls(
            current=int(d.get("current", 0)),
            headroom=int(d.get("headroom", 0)),
            housing_headroom=int(d.get("housing_headroom", 0)),
        )


@dataclass
class Unit:
    id: int
    type: int
    name: str
    hp: float
    max_hp: float
    x: float
    y: float
    z: float = 0
    idle: bool = False
    moving: bool = False
    unit_class: int = 0

    @property
    def hp_pct(self) -> float:
        return (self.hp / self.max_hp * 100) if self.max_hp > 0 else 0

    def __str__(self) -> str:
        status = "idle" if self.idle else ("moving" if self.moving else "busy")
        return f"{self.name}(#{self.id}) HP:{self.hp:.0f}/{self.max_hp:.0f} @({self.x:.1f},{self.y:.1f}) [{status}]"

    @classmethod
    def from_dict(cls, d: dict) -> Unit:
        return cls(
            id=d["id"], type=d["type"], name=d.get("name", ""),
            hp=d.get("hp", 0), max_hp=d.get("maxHp", 0),
            x=d.get("x", 0), y=d.get("y", 0), z=d.get("z", 0),
            idle=d.get("idle", False), moving=d.get("moving", False),
            unit_class=d.get("class", 0),
        )


@dataclass
class Building:
    id: int
    type: int
    name: str
    hp: float
    max_hp: float
    x: float
    y: float
    z: float = 0

    @classmethod
    def from_dict(cls, d: dict) -> Building:
        return cls(
            id=d["id"], type=d["type"], name=d.get("name", ""),
            hp=d.get("hp", 0), max_hp=d.get("maxHp", 0),
            x=d.get("x", 0), y=d.get("y", 0), z=d.get("z", 0),
        )


@dataclass
class MapTile:
    x: int
    y: int
    terrain: int
    elevation: int
    walkable: bool
    buildable: bool
    visibility: int

    @classmethod
    def from_dict(cls, d: dict) -> MapTile:
        return cls(
            x=d["x"], y=d["y"],
            terrain=d.get("terrain", 0), elevation=d.get("elevation", 0),
            walkable=d.get("walkable", True), buildable=d.get("buildable", True),
            visibility=d.get("visibility", 0),
        )


@dataclass
class Player:
    id: int
    name: str
    civilization: str
    civ_id: int
    is_enemy: bool
    is_ally: bool
    has_won: bool

    @classmethod
    def from_dict(cls, d: dict) -> Player:
        return cls(
            id=d["id"], name=d.get("name", ""),
            civilization=d.get("civilization", ""), civ_id=d.get("civId", 0),
            is_enemy=d.get("isEnemy", False), is_ally=d.get("isAlly", False),
            has_won=d.get("hasWon", False),
        )


@dataclass
class GameState:
    """Snapshot of the full game state from a single get_state call."""
    player_id: int = 0
    time: float = 0
    paused: bool = False
    player_name: str = ""
    civilization: str = ""
    civ_id: int = 0
    age: int = 0
    resources: Resources = field(default_factory=Resources)
    population: Population = field(default_factory=Population)
    villager_count: int = 0
    idle_villagers: int = 0
    helpers_ready: bool = False
    unit_counts: dict[str, int] = field(default_factory=dict)
    building_counts: dict[str, int] = field(default_factory=dict)

    @property
    def age_name(self) -> str:
        return Age.NAMES.get(self.age, f"Unknown({self.age})")

    @property
    def game_time_str(self) -> str:
        minutes = int(self.time) // 60
        seconds = int(self.time) % 60
        return f"{minutes}:{seconds:02d}"

    def summary(self) -> str:
        lines = [
            f"=== {self.player_name} ({self.civilization}) ===",
            f"Time: {self.game_time_str} | Age: {self.age_name} | Pop: {self.population}",
            f"Resources: {self.resources}",
        ]
        if self.unit_counts:
            nonzero = {k: v for k, v in self.unit_counts.items() if v > 0}
            if nonzero:
                lines.append(f"Units: {nonzero}")
        if self.building_counts:
            nonzero = {k: v for k, v in self.building_counts.items() if v > 0}
            if nonzero:
                lines.append(f"Buildings: {nonzero}")
        return "\n".join(lines)

    @classmethod
    def from_dict(cls, d: dict) -> GameState:
        return cls(
            player_id=d.get("playerId", 0),
            time=d.get("time", 0),
            paused=d.get("paused", False),
            player_name=d.get("playerName", ""),
            civilization=d.get("civilization", ""),
            civ_id=d.get("civId", 0),
            age=d.get("age", 0),
            resources=Resources.from_dict(d.get("resources", {})),
            population=Population.from_dict(d.get("population", {})),
            villager_count=d.get("villagerCount", 0),
            idle_villagers=d.get("idleVillagers", 0),
            helpers_ready=d.get("helpersReady", False),
            unit_counts=d.get("unitCounts", {}),
            building_counts=d.get("buildingCounts", {}),
        )
