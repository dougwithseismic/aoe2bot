# AoE2Bot — Claude-Controlled Age of Empires 2 Bot

## Project Structure

```
aoe2bot/
├── game/aoe2bot/              # Lua module (runs inside AoE2Control)
│   └── aoe2bot.main.lua       # IPC bridge + ConstructionPlacement helpers
├── bot/                       # Python package (runs externally)
│   ├── pyproject.toml
│   ├── src/aoe2bot/
│   │   ├── protocol.py        # Wire protocol: command builders, unit/building/tech IDs
│   │   ├── client.py          # TcpClient (bridge) + AoE2Client (named pipe)
│   │   ├── bridge.py          # TCP-to-named-pipe bridge server
│   │   ├── game_state.py      # Typed models: GameState, Unit, Building, MapTile, etc.
│   │   ├── controller.py      # High-level API: train_villager(), smart_build_house(), etc.
│   │   ├── cli.py             # CLI entry point — all output is JSON
│   │   └── strategy/          # Strategy engine (see below)
│   └── scripts/
│       └── install_module.py  # Copies Lua module to AoE2Control's modules dir
├── tools/                     # Reference docs (CONTROL_LUA_ENGINE_REFERENCE.md)
├── docs/                      # Gameplay guide, world-state spec
├── apps/                      # Turborepo apps (docs, web — not bot-related)
└── packages/                  # Turborepo shared packages
```

## Quick Start (Full Session)

The aoe2bot CLI is installed at `C:\Users\GODZILLA\AppData\Roaming\Python\Python313\Scripts\aoe2bot.exe`.
Use the full path or alias it — it's not on PATH.

```powershell
$aoe2bot = "C:\Users\GODZILLA\AppData\Roaming\Python\Python313\Scripts\aoe2bot.exe"

# 1. AoE2:DE must already be running (start a skirmish, pause it)
# 2. Install/update the Lua module
cd bot
python scripts/install_module.py

# 3. Start AoE2Control headless (injects DLL, loads module, exits)
& "E:\WEB_PROJECTS\_CLIENTS\aoe2bot\tools\AoE2Control\AoE2Control.exe" --headless

# 4. Start the TCP bridge (keep running)
& $aoe2bot bridge  # runs in background

# 5. Test connection
& $aoe2bot ping

# 6. Run the strategy
& $aoe2bot run-strategy fast-castle
```

**IMPORTANT ordering:**
- `install_module.py` MUST run BEFORE AoE2Control starts (it copies the Lua file)
- AoE2Control loads the module on startup — it does NOT re-read the file on reload_module
- To update the Lua module mid-session: copy the file, then restart AoE2Control
- The Python package uses editable install (`pip install -e`), so Python code changes are live immediately — just restart the strategy process

### Updating Lua Module Mid-Session
```powershell
# If AoE2Control has a lock on the folder, copy the file directly:
Copy-Item "E:\WEB_PROJECTS\_CLIENTS\aoe2bot\game\aoe2bot\aoe2bot.main.lua" `
  "C:\Users\GODZILLA\AppData\Roaming\CONTROL\AoE2Control\modules\aoe2bot\aoe2bot.main.lua" -Force
# Then restart AoE2Control headless for the new code to take effect
```

## Architecture

```
Claude (CLI/Python)         TCP Bridge              Named Pipe           AoE2:DE
┌─────────────────┐    ┌────────────────┐    ┌────────────────────┐    ┌──────────┐
│  aoe2bot <cmd>  │───►│  bridge.py     │───►│  aoe2bot.main.lua  │───►│  Game    │
│  (TcpClient)    │◄───│  localhost:9999│◄───│  (Lua module)      │◄───│  Engine  │
└─────────────────┘    └────────────────┘    └────────────────────┘    └──────────┘
       JSON/TCP              Proxy              JSON/Named Pipe
```

1. **Bridge** (`aoe2bot bridge`): long-running process that connects to the named pipe and listens on TCP port 9999
2. **CLI** (`aoe2bot <command>`): connects to bridge via TCP, sends command, prints JSON response
3. **Lua module**: runs inside AoE2:DE via AoE2Control, handles commands and reads game state

All CLI output is JSON. Every command returns a JSON object to stdout.

## Strategy Engine

The strategy engine lives in `bot/src/aoe2bot/strategy/` and runs an autonomous game loop.

### World-State Model
```
strategy/
├── world.py           # WorldState orchestrator — single source of truth
├── units.py           # UnitTracker: positions, idle detection, inferred tasks
├── buildings.py       # BuildingTracker: construction progress, completion, type queries
├── commands.py        # CommandTracker: prevents duplicates, verifies outcomes
├── map_knowledge.py   # MapKnowledge: explored tiles, resource discovery/depletion
├── event_queue.py     # EventQueue: priority actions, multi-step sequences, wait conditions
├── spatial.py         # SpatialEngine: base layout, placement goals, farm rings
├── eco.py             # EcoManager: age-aware vil distribution, wood-first fallback
├── fast_castle.py     # FastCastleStrategy: adaptive goal-based strategy
├── runner.py          # StrategyRunner: game loop with enrichment + logging
├── actions.py         # Priority tiers (CRITICAL=100, URGENT=80, HIGH=60, NORMAL=40, LOW=20)
├── state.py           # AdaptiveState: computed game state snapshot
└── base.py            # BaseStrategy ABC
```

### How It Works
Each tick (~0.8s), the runner:
1. Polls game state (free IPC read)
2. Enriches with buildings, tech, resources, units (staggered every 5 ticks)
3. Updates WorldState (all trackers)
4. Calls `strategy.on_tick()` — evaluates all candidate actions, queues by priority
5. Calls `queue.tick()` — executes the single highest-priority action (1 command/tick constraint)

### Priority Tiers
| Priority | Value | Examples |
|----------|-------|---------|
| CRITICAL | 100 | Build TC if none exists, build house if pop-blocked |
| URGENT | 80 | Train villager, advance age, build farm when starving |
| HIGH | 60 | Assign idle vils, enable scouting, key eco buildings |
| NORMAL | 40 | Research techs, military buildings |
| LOW | 20 | Extra houses, eco techs |

## Critical Lessons (from live testing)

### Building Placement
- **ALWAYS use `ConstructionPlacement:BuildStructure()`** — the Lua `cmdPlaceBuilding` uses this as primary method. It validates the full building footprint (TC is 4x4), auto-finds valid nearby positions, and assigns builders.
- `UnitsBuildStructure()` returns `true` even when the game silently rejects the placement (e.g., footprint overlaps a bush). Never trust its return value alone.
- Single-tile `IsBuildable()` is NOT sufficient for multi-tile buildings.

### Town Center Specifics
- Use `place_building("TOWN_CENTER")` — the Lua `resolveBuildingType()` automatically picks `TOWN_CENTER_FOUNDATION` (621) when no TC exists, or the age-appropriate type otherwise.
- **Never hardcode `TOWN_CENTER_FOUNDATION`** — it becomes unavailable after the first TC is built.
- TC appears as 4 separate building entries: "(Front)", "(Back)", "(Main)", "(Center)".
- Check `spatial.layout.tc_pos` (from `get_town_centers` IPC) — more reliable than BuildingTracker for TC detection.

### Commands Are Async
- Game commands are fire-and-forget. Vils must walk to the build site, then build.
- **Wait 15-30 seconds** before checking if a building appeared.
- Don't spam the same command — use CommandTracker to prevent duplicates.

### Scouting
- `EnableScouting()` (IPC action `scout`) auto-scouts with the scout unit. One command, game handles the rest.
- Scouting is essential — ResourceTracker only sees explored resources. No scouting = no trees found = no wood assignment.

### Unit Classes
- 904 = Villagers
- 903 = Buildings (also report as "idle")
- 958 = Livestock (sheep, goats)
- 961 = Scout units

### Resource Scan
- `scan_resources` returns trees, gold, stone, forage (berries) with IDs and positions
- `scan_livestock` returns owned + convertible livestock
- Resources deplete — always rescan, never cache IDs long-term
- `treeCount: 0` is normal if area hasn't been scouted or trees were chopped

## CLI Commands (all return JSON)

```bash
# State queries
aoe2bot ping                           # Test connection
aoe2bot status                         # Full game state snapshot
aoe2bot resources                      # Current food/wood/gold/stone
aoe2bot units                          # List all owned units with positions
aoe2bot idle-vils                      # List idle villagers
aoe2bot buildings                      # List all buildings
aoe2bot town-centers                   # List town centers
aoe2bot players                        # List all players with relations
aoe2bot map-info                       # Get map dimensions
aoe2bot diag                           # Run diagnostics (check helpers, enums)

# Smart building (auto-placement via ConstructionPlacement)
aoe2bot smart-build house              # Build house near TC (auto-finds spot)
aoe2bot smart-build farm               # Build farm (auto-placement)
aoe2bot smart-build barracks           # Build barracks near TC

# Manual building (uses ConstructionPlacement for footprint validation)
aoe2bot build house 120.5 85.3         # Build near these coordinates
aoe2bot build farm 100 90

# Training
aoe2bot train villager                 # Train 1 villager
aoe2bot train archer -n 5             # Train 5 archers

# Research
aoe2bot research loom
aoe2bot research feudal

# Unit commands
aoe2bot move 150 200 --units 42 43
aoe2bot attack 99 --units 42 43 44
aoe2bot attack-move 200 200 --units 42 43
aoe2bot scout                          # Enable auto-scouting

# Game control
aoe2bot pause
aoe2bot speed 0.5
aoe2bot camera 100 100
aoe2bot chat "glhf"

# Raw JSON (send any payload)
aoe2bot raw '{"action":"scan_available"}'   # Full tech tree: all buildings/units/techs with costs
aoe2bot raw '{"action":"scan_resources"}'   # Nearby trees/gold/stone/forage with IDs
aoe2bot raw '{"action":"scan_livestock"}'   # Owned + convertible livestock
```

## Unit/Building/Tech Name Aliases

See `bot/src/aoe2bot/cli.py` for the full alias maps. Common ones:
- Units: `vil`, `militia`, `maa`, `archer`, `xbow`, `arb`, `skirm`, `spear`, `pike`, `scout`, `knight`, `treb`, `monk`
- Buildings: `tc`, `house`, `rax`, `range`, `stable`, `lc`, `mc`, `mill`, `farm`, `castle`, `wall`, `tower`
- Techs: `loom`, `feudal`, `castle`, `imperial`, `wheelbarrow`, `fletching`, `forging`, `ballistics`

## Key Constraints

- **Singleplayer only** — AoE2Control disables multiplayer to protect ranked integrity
- **Windows only** — named pipes and AoE2:DE are Windows-specific
- **Bridge required** — Claude connects via TCP bridge (`aoe2bot bridge`), not directly to pipes
- **Update tick rate** — Lua module polls every 0.5s by default (configurable down to 0.01s in settings.ini)
- **Sequential actions** — by default AoE2Control executes one successful command per update tick
- **Anti-tampering** — AoE2:DE may flag DLL injection; add AoE2Control folder to antivirus exclusions

## AoE2Control Headless Mode

For scripted startup (no GUI):
```powershell
& "E:\WEB_PROJECTS\_CLIENTS\aoe2bot\tools\AoE2Control\AoE2Control.exe" --headless
```
- Age of Empires II must already be running
- Outputs status lines to stdout: `Scanning...`, `Ready`, etc.
- Exit codes: 0=success, 1=already running, 2=bad args, 3=override failed, 4=startup failed
- Module is loaded on startup from `%APPDATA%\CONTROL\AoE2Control\modules\aoe2bot\`
