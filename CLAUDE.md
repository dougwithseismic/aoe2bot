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
│   │   └── cli.py             # CLI entry point — all output is JSON
│   └── scripts/
│       └── install_module.py  # Copies Lua module to AoE2Control's modules dir
├── tools/                     # Reference docs (CONTROL_LUA_ENGINE_REFERENCE.md)
├── apps/                      # Turborepo apps (docs, web — not bot-related)
└── packages/                  # Turborepo shared packages
```

## Setup

### Prerequisites
- AoE2:DE (Definitive Edition) installed
- AoE2Control v0.9.1+ downloaded from https://github.com/aoe2control/AoE2Control/releases
  - Archive password: `control`
  - Add folder exception in Windows Defender (DLL injection triggers false positive)
- Python 3.11+

### Install Python Package
```powershell
cd bot
pip install -e ".[dev]"
```

### Install Lua Module into AoE2Control
```powershell
python bot/scripts/install_module.py
```
This copies `game/aoe2bot/` to `%APPDATA%\CONTROL\AoE2Control\modules\aoe2bot\`.

### Connect to Game
1. Launch AoE2:DE
2. Run `AoE2Control.exe` → click START (or `--headless` for scripted startup)
3. In AoE2Control, assign `aoe2bot` module to a bot player slot
4. Start a singleplayer game (skirmish vs AI)
5. Start the TCP bridge: `aoe2bot bridge`
6. Test: `aoe2bot ping`

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

## How Claude Controls the Game

### Start the bridge (run once, keep running)
```powershell
aoe2bot bridge
```

### CLI Commands (all return JSON)
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
aoe2bot smart-build house 120 85       # Build house near specific position
aoe2bot find-placement house           # Find best spot WITHOUT building
aoe2bot queue-build house --priority 8 # Queue with priority (processed each tick)

# Manual building (exact coordinates)
aoe2bot build house 120.5 85.3         # Build house at exact coordinates
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
aoe2bot scout

# Game control
aoe2bot pause
aoe2bot speed 0.5
aoe2bot camera 100 100
aoe2bot chat "glhf"

# Raw JSON (send any payload)
aoe2bot raw '{"action":"enum_lookup","table_name":"UnitObjectType","search":"HOUSE"}'
```

### Python API
```python
from aoe2bot.controller import GameController

# TCP mode (connects to bridge)
ctrl = GameController(tcp_host="127.0.0.1", tcp_port=9999)
ctrl.connect()

state = ctrl.get_state()

# Smart building — no coordinates needed
ctrl.smart_build_house()    # auto-places near TC
ctrl.smart_build_farm()
ctrl.smart_build_barracks()

# Economy
ctrl.train_villager(3)
ctrl.research_loom()

# Military
ctrl.train_archer(5)
ctrl.train_knight(3)
ctrl.auto_scout()

ctrl.disconnect()
```

## Lua Module Helpers

The Lua module initializes three CONTROL helper objects on `Init()`:

- **ResourceTracker** — tracks resource nodes (trees, gold, stone, forage, livestock)
- **VillagerOccupation** — manages villager assignment and idle detection
- **ConstructionPlacement** — auto-finds valid building positions, manages build queues

These are updated every `Update()` tick. The `smart_build`, `find_placement`, and `queue_build` actions use `ConstructionPlacement` to handle placement logic so Claude doesn't need to guess coordinates.

`diag` command reports whether helpers initialized successfully (`helpersReady` field).

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
AoE2Control.exe --headless [--override-settings settings.ini] [--override-module path]
```
- Age of Empires II must already be running
- Outputs status lines to stdout: `Scanning...`, `Ready`, etc.
- Exit codes: 0=success, 1=already running, 2=bad args, 3=override failed, 4=startup failed
