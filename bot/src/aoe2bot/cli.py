"""CLI entry point for AoE2Bot — used by Claude to control the game.

All output is JSON to stdout. Connects via TCP bridge by default.
Start the bridge first: aoe2bot bridge
"""

from __future__ import annotations

import sys
import json
import argparse

from .controller import GameController
from .client import TcpClient
from .protocol import UnitType, BuildingType, Technology


def main():
    parser = argparse.ArgumentParser(
        description="AoE2Bot CLI — control AoE2:DE via TCP bridge (JSON output)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bridge host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=9999, help="Bridge port (default: 9999)")
    parser.add_argument("--pipe", default=None, help="Connect directly to named pipe instead of TCP bridge")
    parser.add_argument("--player", type=int, default=None, help="Target player ID")

    sub = parser.add_subparsers(dest="command", required=True)

    # Bridge server
    p_bridge = sub.add_parser("bridge", help="Start the TCP-to-pipe bridge server")
    p_bridge.add_argument("--bridge-host", default="127.0.0.1")
    p_bridge.add_argument("--bridge-port", type=int, default=9999)

    # State queries
    sub.add_parser("ping", help="Test connection")
    sub.add_parser("status", help="Full game state snapshot")
    sub.add_parser("resources", help="Current resources")
    sub.add_parser("units", help="List all owned units")
    sub.add_parser("idle-vils", help="List idle villagers")
    sub.add_parser("military", help="List military units")
    sub.add_parser("buildings", help="List all buildings")
    sub.add_parser("town-centers", help="List town centers")
    sub.add_parser("players", help="List all players")
    sub.add_parser("map-info", help="Map dimensions")
    sub.add_parser("diag", help="Run diagnostics on Lua module")

    p_tiles = sub.add_parser("map-tiles", help="Tile data for a region")
    p_tiles.add_argument("x1", type=int)
    p_tiles.add_argument("y1", type=int)
    p_tiles.add_argument("x2", type=int)
    p_tiles.add_argument("y2", type=int)

    # Training
    p_train = sub.add_parser("train", help="Train a unit")
    p_train.add_argument("unit", help="Unit name or type ID")
    p_train.add_argument("--amount", "-n", type=int, default=1)

    # Building (raw coordinates)
    p_build = sub.add_parser("build", help="Build at exact coordinates")
    p_build.add_argument("building", help="Building name or type ID")
    p_build.add_argument("x", type=float)
    p_build.add_argument("y", type=float)
    p_build.add_argument("--builders", nargs="*", type=int)

    # Smart building (auto-placement)
    p_sbuild = sub.add_parser("smart-build", help="Auto-place a building (uses ConstructionPlacement)")
    p_sbuild.add_argument("building", help="Building name (house, farm, barracks, etc.)")
    p_sbuild.add_argument("x", type=float, nargs="?", default=None, help="Optional target X")
    p_sbuild.add_argument("y", type=float, nargs="?", default=None, help="Optional target Y")
    p_sbuild.add_argument("--padding", type=int, default=1)

    # Find placement (query only, no build)
    p_fplace = sub.add_parser("find-placement", help="Find best building position without building")
    p_fplace.add_argument("building", help="Building name")
    p_fplace.add_argument("x", type=float, nargs="?", default=None)
    p_fplace.add_argument("y", type=float, nargs="?", default=None)
    p_fplace.add_argument("--padding", type=int, default=1)

    # Queue building
    p_qbuild = sub.add_parser("queue-build", help="Queue a building request with priority")
    p_qbuild.add_argument("building", help="Building name")
    p_qbuild.add_argument("--priority", type=int, default=5)
    p_qbuild.add_argument("--padding", type=int, default=1)

    # Research
    p_research = sub.add_parser("research", help="Research a technology")
    p_research.add_argument("tech", help="Technology name or ID")

    # Unit commands
    p_move = sub.add_parser("move", help="Move units to position")
    p_move.add_argument("x", type=float)
    p_move.add_argument("y", type=float)
    p_move.add_argument("--units", nargs="+", type=int, required=True)

    p_attack = sub.add_parser("attack", help="Attack a target")
    p_attack.add_argument("target_id", type=int)
    p_attack.add_argument("--units", nargs="+", type=int, required=True)

    p_amove = sub.add_parser("attack-move", help="Attack-move to position")
    p_amove.add_argument("x", type=float)
    p_amove.add_argument("y", type=float)
    p_amove.add_argument("--units", nargs="+", type=int, required=True)

    p_patrol = sub.add_parser("patrol", help="Patrol to position")
    p_patrol.add_argument("x", type=float)
    p_patrol.add_argument("y", type=float)
    p_patrol.add_argument("--units", nargs="+", type=int, required=True)

    sub.add_parser("scout", help="Auto-scout with idle scout")

    p_stance = sub.add_parser("stance", help="Set unit combat stance")
    p_stance.add_argument("stance", choices=["aggressive", "defensive", "no-attack", "stand-ground"])
    p_stance.add_argument("--units", nargs="+", type=int, required=True)

    p_gather = sub.add_parser("gather-point", help="Set building gather point")
    p_gather.add_argument("x", type=float)
    p_gather.add_argument("y", type=float)
    p_gather.add_argument("--buildings", nargs="+", type=int, required=True)

    # Game control
    sub.add_parser("pause", help="Pause the game")
    sub.add_parser("unpause", help="Unpause the game")

    p_speed = sub.add_parser("speed", help="Set game speed")
    p_speed.add_argument("multiplier", type=float)

    p_camera = sub.add_parser("camera", help="Move camera")
    p_camera.add_argument("x", type=float)
    p_camera.add_argument("y", type=float)

    p_chat = sub.add_parser("chat", help="Send chat message")
    p_chat.add_argument("message")

    p_afford = sub.add_parser("can-afford", help="Check affordability")
    p_afford.add_argument("unit", help="Unit/building name or type ID")
    p_afford.add_argument("--building", action="store_true")

    p_path = sub.add_parser("find-path", help="Find path between two points")
    p_path.add_argument("x1", type=float)
    p_path.add_argument("y1", type=float)
    p_path.add_argument("x2", type=float)
    p_path.add_argument("y2", type=float)

    sub.add_parser("resign", help="Resign the game")

    # Strategy runner
    p_strat = sub.add_parser("run-strategy", help="Run an automated strategy")
    p_strat.add_argument("strategy", choices=["fast-castle"], help="Strategy name")
    p_strat.add_argument("--tick", type=float, default=0.8, help="Tick interval in seconds")
    p_strat.add_argument("--speed", type=float, default=None, help="Set game speed before starting")

    # Raw JSON
    p_raw = sub.add_parser("raw", help="Send raw JSON payload")
    p_raw.add_argument("payload", help="JSON string")

    args = parser.parse_args()

    # Bridge subcommand — starts the server, doesn't need a game connection
    if args.command == "bridge":
        from .bridge import main as bridge_main
        bridge_main(host=args.bridge_host, port=args.bridge_port, pipe_name=args.pipe, target_player=args.player)
        return

    # Strategy runner — manages its own connection and loop
    if args.command == "run-strategy":
        from .strategy import StrategyRunner, FastCastleStrategy
        ctrl = GameController(tcp_host=args.host, tcp_port=args.port, target_player=args.player)
        if args.speed:
            ctrl.connect()
            ctrl.set_speed(args.speed)
        strategy = FastCastleStrategy(ctrl)
        runner = StrategyRunner(ctrl, strategy, tick_interval=args.tick)
        runner.run()
        return

    # All other commands connect to the bridge (or pipe) and dispatch
    if args.pipe:
        ctrl = GameController(pipe_name=args.pipe, target_player=args.player)
    else:
        ctrl = GameController(tcp_host=args.host, tcp_port=args.port, target_player=args.player)

    try:
        ctrl.connect()
    except Exception as e:
        _out({"ok": False, "error": str(e)})
        sys.exit(1)

    try:
        result = dispatch(ctrl, args)
        _out(result)
    except Exception as e:
        _out({"ok": False, "error": str(e)})
        sys.exit(1)
    finally:
        ctrl.disconnect()


def _out(data):
    """Print JSON to stdout."""
    if isinstance(data, str):
        data = {"ok": True, "message": data}
    elif isinstance(data, list):
        data = {"ok": True, "items": data}
    if isinstance(data, dict) and "ok" not in data:
        data["ok"] = True
    print(json.dumps(data, indent=2, default=str))


def dispatch(ctrl: GameController, args):
    cmd = args.command

    if cmd == "ping":
        return ctrl.client.request({"action": "ping"})

    elif cmd == "status":
        return ctrl.client.request({"action": "get_state"})

    elif cmd == "resources":
        state = ctrl.client.request({"action": "get_state"})
        return {"resources": state.get("resources", {})}

    elif cmd == "units":
        return ctrl.client.request({"action": "get_units"})

    elif cmd == "idle-vils":
        resp = ctrl.client.request({"action": "get_units"})
        idle = [u for u in resp.get("units", []) if u.get("idle")]
        return {"count": len(idle), "units": idle}

    elif cmd == "military":
        resp = ctrl.client.request({"action": "get_units"})
        mil = [u for u in resp.get("units", []) if u.get("class") not in (4, 58)]  # not villager/building
        return {"count": len(mil), "units": mil}

    elif cmd == "buildings":
        return ctrl.client.request({"action": "get_buildings"})

    elif cmd == "town-centers":
        return ctrl.client.request({"action": "get_town_centers"})

    elif cmd == "players":
        return ctrl.client.request({"action": "get_players"})

    elif cmd == "map-info":
        return ctrl.client.request({"action": "get_map"})

    elif cmd == "map-tiles":
        return ctrl.client.request({"action": "get_map_tiles", "x1": args.x1, "y1": args.y1, "x2": args.x2, "y2": args.y2})

    elif cmd == "diag":
        return ctrl.client.request({"action": "diag"})

    elif cmd == "train":
        unit_type = resolve_unit_type(args.unit)
        return ctrl.client.request({"action": "train", "unit_type": unit_type, "amount": args.amount})

    elif cmd == "build":
        building_type = resolve_building_type(args.building)
        msg = {"action": "build", "building_type": building_type, "x": args.x, "y": args.y}
        if args.builders:
            msg["builder_ids"] = args.builders
        return ctrl.client.request(msg)

    elif cmd == "smart-build":
        building_name = resolve_building_enum_name(args.building)
        return ctrl.client.request({"action": "smart_build", "building_name": building_name, "x": args.x, "y": args.y, "padding": args.padding})

    elif cmd == "find-placement":
        building_name = resolve_building_enum_name(args.building)
        return ctrl.client.request({"action": "find_placement", "building_name": building_name, "x": args.x, "y": args.y, "padding": args.padding})

    elif cmd == "queue-build":
        building_name = resolve_building_enum_name(args.building)
        return ctrl.client.request({"action": "queue_build", "building_name": building_name, "priority": args.priority, "padding": args.padding})

    elif cmd == "research":
        tech_id = resolve_technology(args.tech)
        return ctrl.client.request({"action": "research", "technology": tech_id})

    elif cmd == "move":
        return ctrl.client.request({"action": "move", "unit_ids": args.units, "x": args.x, "y": args.y})

    elif cmd == "attack":
        return ctrl.client.request({"action": "attack", "unit_ids": args.units, "target_id": args.target_id})

    elif cmd == "attack-move":
        return ctrl.client.request({"action": "attack_move", "unit_ids": args.units, "x": args.x, "y": args.y})

    elif cmd == "patrol":
        return ctrl.client.request({"action": "patrol", "unit_ids": args.units, "x": args.x, "y": args.y})

    elif cmd == "scout":
        return ctrl.client.request({"action": "scout"})

    elif cmd == "stance":
        stance_map = {"aggressive": 0, "defensive": 1, "no-attack": 2, "stand-ground": 3}
        return ctrl.client.request({"action": "set_stance", "unit_ids": args.units, "stance": stance_map[args.stance]})

    elif cmd == "gather-point":
        return ctrl.client.request({"action": "set_gather_point", "building_ids": args.buildings, "x": args.x, "y": args.y})

    elif cmd == "pause":
        return ctrl.client.request({"action": "pause"})

    elif cmd == "unpause":
        return ctrl.client.request({"action": "unpause"})

    elif cmd == "speed":
        return ctrl.client.request({"action": "set_speed", "speed": args.multiplier})

    elif cmd == "camera":
        return ctrl.client.request({"action": "set_camera", "x": args.x, "y": args.y})

    elif cmd == "chat":
        return ctrl.client.request({"action": "chat", "message": args.message})

    elif cmd == "can-afford":
        unit_type = resolve_unit_type(args.unit) if not args.building else resolve_building_type(args.unit)
        return ctrl.client.request({"action": "can_afford", "unit_type": unit_type, "is_building": args.building})

    elif cmd == "find-path":
        return ctrl.client.request({"action": "find_path", "x1": args.x1, "y1": args.y1, "x2": args.x2, "y2": args.y2})

    elif cmd == "resign":
        return ctrl.client.request({"action": "resign"})

    elif cmd == "raw":
        payload = json.loads(args.payload)
        return ctrl.client.request(payload)

    return {"ok": False, "error": f"unknown command: {cmd}"}


# ── Name Resolution ──────────────────────────────────────────────────────────

UNIT_NAMES = {
    "villager": UnitType.VILLAGER, "vil": UnitType.VILLAGER,
    "militia": UnitType.MILITIA, "maa": UnitType.MAN_AT_ARMS, "man-at-arms": UnitType.MAN_AT_ARMS,
    "longsword": UnitType.LONG_SWORDSMAN, "2hs": UnitType.TWO_HANDED_SWORDSMAN,
    "champion": UnitType.CHAMPION,
    "spearman": UnitType.SPEARMAN, "spear": UnitType.SPEARMAN,
    "pikeman": UnitType.PIKEMAN, "pike": UnitType.PIKEMAN,
    "archer": UnitType.ARCHER, "xbow": UnitType.CROSSBOWMAN, "crossbow": UnitType.CROSSBOWMAN,
    "arbalester": UnitType.ARBALESTER, "arb": UnitType.ARBALESTER,
    "skirmisher": UnitType.SKIRMISHER, "skirm": UnitType.SKIRMISHER,
    "ca": UnitType.CAVALRY_ARCHER, "cav-archer": UnitType.CAVALRY_ARCHER,
    "scout": UnitType.SCOUT_CAVALRY, "light-cav": UnitType.LIGHT_CAVALRY,
    "knight": UnitType.KNIGHT, "cavalier": UnitType.CAVALIER, "paladin": UnitType.PALADIN,
    "camel": UnitType.CAMEL_RIDER,
    "ram": UnitType.BATTERING_RAM, "capped-ram": UnitType.CAPPED_RAM,
    "mangonel": UnitType.MANGONEL, "onager": UnitType.ONAGER,
    "scorpion": UnitType.SCORPION,
    "trebuchet": UnitType.TREBUCHET, "treb": UnitType.TREBUCHET,
    "monk": UnitType.MONK,
    "trade-cart": UnitType.TRADE_CART,
}

BUILDING_NAMES = {
    "tc": BuildingType.TOWN_CENTER, "town-center": BuildingType.TOWN_CENTER,
    "house": BuildingType.HOUSE,
    "mill": BuildingType.MILL,
    "lumber-camp": BuildingType.LUMBER_CAMP, "lc": BuildingType.LUMBER_CAMP,
    "mining-camp": BuildingType.MINING_CAMP, "mc": BuildingType.MINING_CAMP,
    "farm": BuildingType.FARM,
    "barracks": BuildingType.BARRACKS, "rax": BuildingType.BARRACKS,
    "archery-range": BuildingType.ARCHERY_RANGE, "range": BuildingType.ARCHERY_RANGE,
    "stable": BuildingType.STABLE,
    "siege-workshop": BuildingType.SIEGE_WORKSHOP, "sw": BuildingType.SIEGE_WORKSHOP,
    "blacksmith": BuildingType.BLACKSMITH,
    "market": BuildingType.MARKET,
    "monastery": BuildingType.MONASTERY,
    "university": BuildingType.UNIVERSITY, "uni": BuildingType.UNIVERSITY,
    "castle": BuildingType.CASTLE,
    "dock": BuildingType.DOCK,
    "watch-tower": BuildingType.WATCH_TOWER, "tower": BuildingType.WATCH_TOWER,
    "guard-tower": BuildingType.GUARD_TOWER,
    "keep": BuildingType.KEEP,
    "stone-wall": BuildingType.STONE_WALL, "wall": BuildingType.STONE_WALL,
    "palisade": BuildingType.PALISADE_WALL, "palisade-wall": BuildingType.PALISADE_WALL,
    "gate": BuildingType.GATE,
    "outpost": BuildingType.OUTPOST,
    "wonder": BuildingType.WONDER,
}

# Maps CLI-friendly names to UnitObjectType enum member names (as used in Lua)
BUILDING_ENUM_NAMES = {
    "house": "HOUSE", "tc": "TOWN_CENTER", "town-center": "TOWN_CENTER",
    "mill": "MILL", "farm": "FARM",
    "lumber-camp": "LUMBER_CAMP", "lc": "LUMBER_CAMP",
    "mining-camp": "MINING_CAMP", "mc": "MINING_CAMP",
    "barracks": "BARRACKS", "rax": "BARRACKS",
    "archery-range": "ARCHERY_RANGE", "range": "ARCHERY_RANGE",
    "stable": "STABLE",
    "siege-workshop": "SIEGE_WORKSHOP", "sw": "SIEGE_WORKSHOP",
    "blacksmith": "BLACKSMITH", "market": "MARKET",
    "monastery": "MONASTERY", "university": "UNIVERSITY", "uni": "UNIVERSITY",
    "castle": "CASTLE", "dock": "DOCK",
    "watch-tower": "WATCH_TOWER", "tower": "WATCH_TOWER",
    "guard-tower": "GUARD_TOWER", "keep": "KEEP",
    "stone-wall": "STONE_WALL", "wall": "STONE_WALL",
    "palisade": "PALISADE_WALL", "palisade-wall": "PALISADE_WALL",
    "gate": "GATE", "outpost": "OUTPOST", "wonder": "WONDER",
}

TECH_NAMES = {
    "loom": Technology.LOOM,
    "feudal": Technology.FEUDAL_AGE, "feudal-age": Technology.FEUDAL_AGE,
    "castle": Technology.CASTLE_AGE, "castle-age": Technology.CASTLE_AGE,
    "imperial": Technology.IMPERIAL_AGE, "imperial-age": Technology.IMPERIAL_AGE,
    "wheelbarrow": Technology.WHEELBARROW, "wb": Technology.WHEELBARROW,
    "hand-cart": Technology.HAND_CART, "hc": Technology.HAND_CART,
    "double-bit-axe": Technology.DOUBLE_BIT_AXE,
    "bow-saw": Technology.BOW_SAW,
    "horse-collar": Technology.HORSE_COLLAR,
    "heavy-plow": Technology.HEAVY_PLOW,
    "gold-mining": Technology.GOLD_MINING,
    "stone-mining": Technology.STONE_MINING,
    "fletching": Technology.FLETCHING,
    "bodkin": Technology.BODKIN_ARROW,
    "bracer": Technology.BRACER,
    "forging": Technology.FORGING,
    "iron-casting": Technology.IRON_CASTING,
    "blast-furnace": Technology.BLAST_FURNACE,
    "ballistics": Technology.BALLISTICS,
    "chemistry": Technology.CHEMISTRY,
    "murder-holes": Technology.MURDER_HOLES,
    "masonry": Technology.MASONRY,
    "architecture": Technology.ARCHITECTURE,
    "town-watch": Technology.TOWN_WATCH,
    "town-patrol": Technology.TOWN_PATROL,
    "conscription": Technology.CONSCRIPTION,
    "husbandry": Technology.HUSBANDRY,
}


def resolve_unit_type(name: str) -> int:
    lower = name.lower().strip()
    if lower in UNIT_NAMES:
        return UNIT_NAMES[lower]
    try:
        return int(name)
    except ValueError:
        raise ValueError(f"Unknown unit type: '{name}'. Known: {', '.join(sorted(UNIT_NAMES.keys()))}")


def resolve_building_type(name: str) -> int:
    lower = name.lower().strip()
    if lower in BUILDING_NAMES:
        return BUILDING_NAMES[lower]
    try:
        return int(name)
    except ValueError:
        raise ValueError(f"Unknown building: '{name}'. Known: {', '.join(sorted(BUILDING_NAMES.keys()))}")


def resolve_building_enum_name(name: str) -> str:
    lower = name.lower().strip()
    if lower in BUILDING_ENUM_NAMES:
        return BUILDING_ENUM_NAMES[lower]
    return name.upper()


def resolve_technology(name: str) -> int:
    lower = name.lower().strip()
    if lower in TECH_NAMES:
        return TECH_NAMES[lower]
    try:
        return int(name)
    except ValueError:
        raise ValueError(f"Unknown tech: '{name}'. Known: {', '.join(sorted(TECH_NAMES.keys()))}")


if __name__ == "__main__":
    main()
