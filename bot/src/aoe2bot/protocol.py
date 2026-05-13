"""Wire protocol constants and command builders for AoE2Control IPC."""

from __future__ import annotations

PIPE_NAME = r"\\.\pipe\AoE2Bot_Pipe"


# ── Unit Object Types (subset — extend as needed) ────────────────────────────

class UnitType:
    VILLAGER = 83
    MILITIA = 74
    MAN_AT_ARMS = 75
    LONG_SWORDSMAN = 77
    TWO_HANDED_SWORDSMAN = 473
    CHAMPION = 567
    SPEARMAN = 93
    PIKEMAN = 358
    ARCHER = 4
    CROSSBOWMAN = 24
    ARBALESTER = 492
    SKIRMISHER = 7
    ELITE_SKIRMISHER = 6
    CAVALRY_ARCHER = 39
    SCOUT_CAVALRY = 448
    LIGHT_CAVALRY = 546
    KNIGHT = 38
    CAVALIER = 283
    PALADIN = 569
    CAMEL_RIDER = 329
    BATTERING_RAM = 35
    CAPPED_RAM = 422
    MANGONEL = 280
    ONAGER = 550
    SCORPION = 279
    TREBUCHET = 42
    TREBUCHET_PACKED = 331
    MONK = 125
    TRADE_CART = 814
    FISHING_SHIP = 13
    GALLEY = 539
    FIRE_GALLEY = 529
    DEMOLITION_RAFT = 1104
    TRANSPORT_SHIP = 545


# ── Building Types ────────────────────────────────────────────────────────────

class BuildingType:
    TOWN_CENTER = 109
    HOUSE = 70
    MILL = 68
    LUMBER_CAMP = 562
    MINING_CAMP = 584
    FARM = 50
    BARRACKS = 12
    ARCHERY_RANGE = 87
    STABLE = 101
    SIEGE_WORKSHOP = 49
    BLACKSMITH = 103
    MARKET = 84
    MONASTERY = 104
    UNIVERSITY = 209
    CASTLE = 82
    DOCK = 45
    WATCH_TOWER = 79
    GUARD_TOWER = 234
    KEEP = 235
    BOMBARD_TOWER = 236
    STONE_WALL = 117
    PALISADE_WALL = 72
    GATE = 487
    OUTPOST = 598
    WONDER = 276


# ── Technologies (common ones) ───────────────────────────────────────────────

class Technology:
    LOOM = 22
    FEUDAL_AGE = 101
    CASTLE_AGE = 102
    IMPERIAL_AGE = 103
    WHEELBARROW = 213
    HAND_CART = 249
    DOUBLE_BIT_AXE = 202
    BOW_SAW = 203
    TWO_MAN_SAW = 221
    HORSE_COLLAR = 14
    HEAVY_PLOW = 13
    CROP_ROTATION = 12
    GOLD_MINING = 55
    GOLD_SHAFT_MINING = 182
    STONE_MINING = 278
    STONE_SHAFT_MINING = 279
    FLETCHING = 199
    BODKIN_ARROW = 200
    BRACER = 201
    FORGING = 67
    IRON_CASTING = 68
    BLAST_FURNACE = 75
    SCALE_MAIL = 74
    CHAIN_MAIL = 76
    PLATE_MAIL = 77
    SCALE_BARDING = 81
    CHAIN_BARDING = 82
    PLATE_BARDING = 80
    PADDED_ARCHER_ARMOR = 211
    LEATHER_ARCHER_ARMOR = 212
    RING_ARCHER_ARMOR = 219
    BALLISTICS = 93
    CHEMISTRY = 47
    MURDER_HOLES = 194
    MASONRY = 50
    ARCHITECTURE = 51
    TOWN_WATCH = 8
    TOWN_PATROL = 280
    CONSCRIPTION = 315
    HUSBANDRY = 39


# ── Combat Stances ────────────────────────────────────────────────────────────

class CombatStance:
    AGGRESSIVE = 0
    DEFENSIVE = 1
    NO_ATTACK = 2
    STAND_GROUND = 3


# ── Player Attributes ────────────────────────────────────────────────────────

class PlayerAttribute:
    FOOD = 0
    WOOD = 1
    STONE = 2
    GOLD = 3
    POP_SPACE_LEFT = 4
    POP_CURRENT = 11
    AGE = 21


# ── Ages ──────────────────────────────────────────────────────────────────────

class Age:
    DARK = 0
    FEUDAL = 1
    CASTLE = 2
    IMPERIAL = 3

    NAMES = {0: "Dark Age", 1: "Feudal Age", 2: "Castle Age", 3: "Imperial Age"}


# ── Command Builders ─────────────────────────────────────────────────────────

def cmd_ping():
    return {"action": "ping"}

def cmd_get_state():
    return {"action": "get_state"}

def cmd_get_resources():
    return {"action": "get_resources"}

def cmd_get_units(unit_type: int | None = None, unit_class: int | None = None):
    msg = {"action": "get_units"}
    if unit_type is not None:
        msg["unit_type"] = unit_type
    if unit_class is not None:
        msg["unit_class"] = unit_class
    return msg

def cmd_get_buildings():
    return {"action": "get_buildings"}

def cmd_get_map():
    return {"action": "get_map"}

def cmd_get_map_tiles(x1: int = 0, y1: int = 0, x2: int = 50, y2: int = 50):
    return {"action": "get_map_tiles", "x1": x1, "y1": y1, "x2": x2, "y2": y2}

def cmd_get_players():
    return {"action": "get_players"}

def cmd_get_tech_state(technologies: list[int]):
    return {"action": "get_tech_state", "technologies": technologies}

def cmd_train(unit_type: int, amount: int = 1):
    return {"action": "train", "unit_type": unit_type, "amount": amount}

def cmd_build(building_type: int, x: float, y: float, builder_ids: list[int] | None = None):
    msg = {"action": "build", "building_type": building_type, "x": x, "y": y}
    if builder_ids:
        msg["builder_ids"] = builder_ids
    return msg

def cmd_research(technology: int):
    return {"action": "research", "technology": technology}

def cmd_move(unit_ids: list[int], x: float, y: float):
    return {"action": "move", "unit_ids": unit_ids, "x": x, "y": y}

def cmd_attack(unit_ids: list[int], target_id: int):
    return {"action": "attack", "unit_ids": unit_ids, "target_id": target_id}

def cmd_attack_move(unit_ids: list[int], x: float, y: float):
    return {"action": "attack_move", "unit_ids": unit_ids, "x": x, "y": y}

def cmd_patrol(unit_ids: list[int], x: float, y: float):
    return {"action": "patrol", "unit_ids": unit_ids, "x": x, "y": y}

def cmd_garrison(unit_ids: list[int], target_id: int):
    return {"action": "garrison", "unit_ids": unit_ids, "target_id": target_id}

def cmd_set_stance(unit_ids: list[int], stance: int):
    return {"action": "set_stance", "unit_ids": unit_ids, "stance": stance}

def cmd_scout():
    return {"action": "scout"}

def cmd_set_camera(x: float, y: float):
    return {"action": "set_camera", "x": x, "y": y}

def cmd_chat(message: str):
    return {"action": "chat", "message": message}

def cmd_can_afford(unit_type: int, is_building: bool = False):
    return {"action": "can_afford", "unit_type": unit_type, "is_building": is_building}

def cmd_find_path(x1: float, y1: float, x2: float, y2: float):
    return {"action": "find_path", "x1": x1, "y1": y1, "x2": x2, "y2": y2}

def cmd_pause():
    return {"action": "pause"}

def cmd_unpause():
    return {"action": "unpause"}

def cmd_set_speed(speed: float):
    return {"action": "set_speed", "speed": speed}

def cmd_resign():
    return {"action": "resign"}

def cmd_set_gather_point(building_ids: list[int], x: float, y: float):
    return {"action": "set_gather_point", "building_ids": building_ids, "x": x, "y": y}


# ── Smart Build (uses ConstructionPlacement) ────────────────────────────────

def cmd_smart_build(building_name: str, x: float | None = None, y: float | None = None, padding: int = 1):
    msg: dict = {"action": "smart_build", "building_name": building_name, "padding": padding}
    if x is not None and y is not None:
        msg["x"] = x
        msg["y"] = y
    return msg

def cmd_find_placement(building_name: str, x: float | None = None, y: float | None = None, padding: int = 1):
    msg: dict = {"action": "find_placement", "building_name": building_name, "padding": padding}
    if x is not None and y is not None:
        msg["x"] = x
        msg["y"] = y
    return msg

def cmd_queue_build(building_name: str, priority: int = 5, padding: int = 1):
    return {"action": "queue_build", "building_name": building_name, "priority": priority, "padding": padding}

def cmd_get_idle_villagers():
    return {"action": "get_units", "unit_class": 4}  # UnitClass.VILLAGER = 4

def cmd_get_town_centers():
    return {"action": "get_town_centers"}


def cmd_get_building_counts():
    return {"action": "get_building_counts"}


def cmd_set_vil_priorities(wood: int, food: int, gold: int, stone: int):
    return {"action": "set_vil_priorities", "wood": wood, "food": food, "gold": gold, "stone": stone}


def cmd_place_building(building_name: str, x: float, y: float):
    return {"action": "place_building", "building_name": building_name, "x": x, "y": y}


def cmd_reload_module():
    return {"action": "reload_module"}
