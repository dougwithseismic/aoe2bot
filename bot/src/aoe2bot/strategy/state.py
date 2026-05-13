"""Adaptive state snapshot -- rich view of current game for strategy decisions."""

from __future__ import annotations

from dataclasses import dataclass, field


def _normalize(s: str) -> str:
    """Strip spaces, underscores, hyphens and uppercase for fuzzy matching.

    "LumberCamp EAST" -> "LUMBERCAMPEAST"
    "LUMBER_CAMP"     -> "LUMBERCAMP"
    """
    return s.upper().replace("_", "").replace(" ", "").replace("-", "")


@dataclass
class AdaptiveState:
    game_time: float = 0.0
    age: int = 0
    food: float = 0.0
    wood: float = 0.0
    gold: float = 0.0
    stone: float = 0.0
    population: int = 0
    housing_headroom: int = 0
    pop_headroom: int = 0
    villager_count: int = 0
    idle_villagers: int = 0
    helpers_ready: bool = False
    buildings: dict[str, int] = field(default_factory=dict)
    tech_state: dict[str, dict] = field(default_factory=dict)
    idle_vil_ids: list[int] = field(default_factory=list)
    resources_scan: dict | None = None

    # -- Computed properties --

    @property
    def game_time_str(self) -> str:
        m, s = divmod(int(self.game_time), 60)
        return f"{m}:{s:02d}"

    @property
    def age_name(self) -> str:
        return {0: "Dark", 1: "Feudal", 2: "Castle", 3: "Imperial"}.get(
            self.age, f"?{self.age}"
        )

    @property
    def needs_houses(self) -> bool:
        return self.housing_headroom <= 3

    @property
    def pop_blocked(self) -> bool:
        return self.housing_headroom <= 0

    @property
    def tc_is_idle(self) -> bool:
        """Approximate -- TC can accept a train command if food/housing allow.

        The actual queue state isn't exposed, so TrainUnit returns false
        if TC already has something queued.
        """
        return self.food >= 50 and self.housing_headroom > 0

    # -- Building queries (fuzzy matching) --

    def _building_count(self, name: str) -> int:
        """Count buildings whose normalized name contains *name*."""
        needle = _normalize(name)
        total = 0
        for key, count in self.buildings.items():
            if needle in _normalize(key):
                total += count
        return total

    def _has_building(self, name: str) -> bool:
        return self._building_count(name) > 0

    @property
    def tc_count(self) -> int:
        return self._building_count("TOWNCENTER")

    @property
    def has_lumber_camp(self) -> bool:
        return self._has_building("LUMBERCAMP")

    @property
    def has_mill(self) -> bool:
        return self._has_building("MILL")

    @property
    def has_barracks(self) -> bool:
        return self._has_building("BARRACKS")

    @property
    def has_blacksmith(self) -> bool:
        return self._has_building("BLACKSMITH")

    @property
    def has_market(self) -> bool:
        return self._has_building("MARKET")

    @property
    def has_stable(self) -> bool:
        return self._has_building("STABLE")

    @property
    def has_archery_range(self) -> bool:
        return self._has_building("ARCHERYRANGE")

    def has_tc_in_progress(self, raw_state: dict) -> bool:
        """Check building details for an incomplete TC."""
        for b in raw_state.get("_building_details", []):
            name = _normalize(b.get("name", ""))
            if "TOWNCENTER" in name and not b.get("complete", False):
                return True
        return False

    # -- Tech queries --

    def is_tech_researched(self, tech_id: int) -> bool:
        entry = self.tech_state.get(str(tech_id), {})
        return entry.get("researched", False)

    def can_research(self, tech_id: int) -> bool:
        entry = self.tech_state.get(str(tech_id), {})
        return entry.get("available", False)

    @property
    def can_click_feudal(self) -> bool:
        return self.age == 0 and self.food >= 500

    @property
    def can_click_castle(self) -> bool:
        return (
            self.age == 1
            and self.food >= 800
            and self.gold >= 200
            and self.has_blacksmith
            and self.has_market
        )

    @property
    def missing_for_castle(self) -> list[str]:
        missing: list[str] = []
        if self.age < 1:
            missing.append("feudal_age")
        if not self.has_blacksmith:
            missing.append("blacksmith")
        if not self.has_market:
            missing.append("market")
        if self.food < 800:
            missing.append(f"food ({800 - self.food:.0f} more)")
        if self.gold < 200:
            missing.append(f"gold ({200 - self.gold:.0f} more)")
        return missing

    # -- Factory --

    @classmethod
    def from_raw(cls, raw: dict) -> AdaptiveState:
        res = raw.get("resources", {})
        pop = raw.get("population", {})
        return cls(
            game_time=raw.get("time", 0),
            age=raw.get("age", 0),
            food=res.get("food", 0),
            wood=res.get("wood", 0),
            gold=res.get("gold", 0),
            stone=res.get("stone", 0),
            population=pop.get("current", 0),
            housing_headroom=pop.get("housing_headroom", 0),
            pop_headroom=pop.get("headroom", 0),
            villager_count=raw.get("villagerCount", 0),
            idle_villagers=raw.get("idleVillagers", 0),
            helpers_ready=raw.get("helpersReady", False),
            buildings=raw.get("_buildings", {}),
            tech_state=raw.get("_tech_state", {}),
            idle_vil_ids=raw.get("_idle_vil_ids", []),
            resources_scan=raw.get("_resources_scan"),
        )
