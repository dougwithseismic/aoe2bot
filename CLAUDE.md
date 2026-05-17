# AoE2Bot — AoE2Control Bot with 22-Pop Scout Rush

## Project Structure

```
aoe2bot/
├── game/aoe2bot/
│   ├── aoe2bot.main.lua       # Lifecycle: session control, wires build order + overlay
│   ├── build_order.lua        # 22-pop scout rush — priority-based state machine
│   ├── overlay.lua            # HUD: game state panel (left) + event log (right)
│   ├── event_log.lua          # Timestamped event buffer (max 20 entries)
│   └── helpers/
│       ├── query.lua          # Read game state: vils, pop, resources, buildings, age
│       ├── spatial.lua        # Distance, footprint check, placement finding, resource search
│       └── command.lua        # Execute actions: train, build, gather, move, research
├── scripts/
│   └── launch.ps1             # Headless launcher (--override-module)
├── tools/
│   ├── AoE2Control/           # Binary (gitignored, download separately)
│   └── CONTROL_LUA_ENGINE_REFERENCE.md
├── .gitignore
├── CLAUDE.md
└── README.md
```

## Quick Start

```powershell
# 1. AoE2:DE must be running (main menu)
# 2. Launch CONTROL headless with the module:
.\scripts\launch.ps1
```

The module auto-configures a 1v1 Arabia skirmish and starts the game. Build order runs automatically.

## Architecture

```
AoE2Control.exe --headless --override-module game/aoe2bot
    └── Injects DLL into AoE2:DE
        └── Loads aoe2bot.main.lua
            ├── Load()   → settings, configure GameOptions, DispatchStartGame()
            ├── Init()   → create ResourceTracker, init build_order
            ├── Update() → rt:Update(), build_order.update(rt)
            ├── Render() → overlay (game state + event log)
            └── End()    → log result
```

## Helper Package (`helpers/`)

Clean patterns — each function wraps ONE pcall at the boundary, returns sensible defaults on failure.

### query.lua — Read Game State
```lua
local query = require("helpers.query")
query.vils()              -- all owned alive villagers (Object[])
query.idle_vils()         -- idle villagers only
query.scout()             -- scout unit or nil
query.tcs()               -- town centers
query.tc_pos()            -- first TC position (Vector2 or nil)
query.pop()               -- {current, headroom, housing, vils}
query.resources()         -- {food, wood, gold, stone}
query.age()               -- 0=Dark, 1=Feudal, 2=Castle, 3=Imperial
query.can_afford(f,w,g,s) -- boolean
query.is_researched(id)   -- boolean
query.can_research(id)    -- boolean
query.buildings("MILL")   -- find buildings matching name pattern
```

### spatial.lua — Distance, Placement, Resource Finding
```lua
local spatial = require("helpers.spatial")
spatial.dist(a, b)                     -- Euclidean distance
spatial.nearest(objects, pos)          -- closest object + distance
spatial.nearest_within(objs, pos, r)   -- closest within radius
spatial.filter_within(objs, pos, r)    -- all within radius
spatial.is_footprint_clear(x, y, size) -- multi-tile buildability check
spatial.find_placement(x, y, size)     -- spiral search for valid spot
spatial.find_safe_trees(rt, tc_pos)    -- trees on safe side (away from center)
spatial.find_food(rt, tc_pos)          -- nearest food: livestock > forage
spatial.find_gold(rt, tc_pos)          -- nearest gold mine
spatial.find_stone(rt, tc_pos)         -- nearest stone mine
```

### command.lua — Execute Actions (auto-logs to event_log)
```lua
local command = require("helpers.command")
command.train_vil()                      -- train from TC
command.build("HOUSE_DARK_AGE", pos)     -- build at position
command.build("HOUSE_DARK_AGE", pos, {v1,v2})  -- specific builders
command.build_near_tc("HOUSE_DARK_AGE", 2)     -- auto-placement near TC
command.gather({vil}, tree)              -- send to resource
command.move({vil}, pos)                 -- move units
command.auto_scout(scout)               -- enable auto-scouting
command.research(22, "Loom")             -- research by numeric ID
```

## Build Order (`build_order.lua`)

Priority-based — each tick, the highest-priority actionable item runs:

| Priority | Actions |
|----------|---------|
| 1 (Critical) | Build house if headroom ≤ 3, train villager if TC idle, enable scouting |
| 2 (Setup) | Force initial vils to food |
| 3 (Eco) | Build lumber camp (7 vils), mill (10 vils), mining camp (20 vils) |
| 4 (Assign) | Send idle vils to resources based on count thresholds |
| 5 (Age up) | Research Loom (20 vils), click Feudal (500 food + 2 buildings) |
| 6 (Maintenance) | Herd far livestock, Feudal eco upgrades |

## Known Working Enum Names

```lua
-- Buildings (bracket notation, age-specific)
UnitObjectType["VILLAGER_MALE"]
UnitObjectType["HOUSE_DARK_AGE"]
UnitObjectType["LUMBER_CAMP_DARK_AGE"]
UnitObjectType["MILL_DARK_AGE"]
UnitObjectType["MINING_CAMP_DARK_AGE"]
UnitObjectType["FARM"]
UnitObjectType["TOWN_CENTER_DARK_AGE"]
UnitObjectType["TOWN_CENTER_FEUDAL_AGE"]
UnitObjectType["BLACKSMITH_FEUDAL_AGE"]
UnitObjectType["MARKET_FEUDAL_AGE"]
UnitObjectType["BARRACKS_DARK_AGE"]

-- Unit classes
UnitClass.VILLAGER  -- 904
-- 903 = buildings, 958 = livestock, 961 = scouts

-- Technologies (numeric IDs)
-- 22 = Loom, 101 = Feudal, 102 = Castle, 103 = Imperial
-- 202 = Double-Bit Axe, 14 = Horse Collar, 213 = Wheelbarrow

-- Facts
Fact.POPULATION, Fact.POPULATION_HEADROOM, Fact.VILLAGER_COUNT
Fact.FOOD_AMOUNT, Fact.WOOD_AMOUNT, Fact.GOLD_AMOUNT, Fact.STONE_AMOUNT
Fact.CURRENT_AGE, Fact.GAME_TIME
```

## Key Constraints

- **One command per tick** when Sequential Actions is enabled
- **Game commands in Update() only**
- **pcall at boundaries** — CONTROL APIs can fail silently; each helper wraps once
- **Module require depth: 3** — `helpers.query` is depth 2, within limit
- **Singleplayer only** — AoE2Control disables multiplayer
- **Footprint validation** — `IsBuildable()` is single-tile; use `spatial.is_footprint_clear()` for multi-tile buildings

## Deploying Changes

```powershell
# Option 1: Restart game (clean load)
# Kill AoE2:DE, relaunch from Steam, then:
.\scripts\launch.ps1

# Option 2: Copy files (requires module reload in CONTROL UI)
Copy-Item "game\aoe2bot\*" "$env:APPDATA\CONTROL\AoE2Control\modules\aoe2bot\" -Recurse -Force
```

## Reference

- Full Lua API: `tools/CONTROL_LUA_ENGINE_REFERENCE.md`
- Official docs: https://aoe2control.github.io/
- Enums: https://aoe2control.github.io/enums/
