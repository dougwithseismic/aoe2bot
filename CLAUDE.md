# AoE2Bot — AoE2Control Bot Boilerplate

## Project Structure

```
aoe2bot/
├── game/aoe2bot/
│   ├── aoe2bot.main.lua       # Main module — lifecycle, session control, bot logic
│   ├── overlay.lua            # HUD overlay — game state panel + event log
│   └── event_log.lua          # Event log — timestamped action history
├── scripts/
│   └── launch.ps1             # Headless launcher (--override-module)
├── tools/
│   ├── AoE2Control/           # Binary (gitignored, download separately)
│   └── CONTROL_LUA_ENGINE_REFERENCE.md  # Full Lua API reference
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

The module auto-configures a skirmish (1v1, Arabia, Hard AI) and starts the game.

## Architecture

```
AoE2Control.exe --headless --override-module game/aoe2bot
    └── Injects DLL into AoE2:DE
        └── Loads aoe2bot.main.lua
            ├── Load()   → configure GameOptions, DispatchStartGame()
            ├── Init()   → match ready, clear event log
            ├── Update() → bot logic each tick (use event_log.add() to log actions)
            ├── Render() → draws overlay (game state + event log)
            └── End()    → match over
```

### Overlay
- **Left panel**: game time, age, population, resources (food/wood/gold/stone)
- **Right panel**: scrolling event log with timestamps

### Event Log Usage
```lua
local event_log = require("event_log")
event_log.add("place barracks at 45,60 with 4 vils [12,13,14,15]")
event_log.add("train villager from TC")
event_log.add("advance to Feudal Age")
```

## Module Lifecycle

| Callback | When | Use for |
|----------|------|---------|
| `Load(playerId)` | Module loaded/enabled | Settings registration, session control |
| `Init()` | Match ready | Per-match setup |
| `Update()` | Every tick (configurable interval) | Game commands, state reads |
| `Render()` | Every frame | Overlays (optional) |
| `End(hasWon)` | Match ends | Cleanup |
| `Unload()` | Module disabled/ejected | Final cleanup |

## Key APIs

### Session Control
```lua
GetCurrentGameOptions()       -- returns GameOptions or nil
DispatchStartGame()           -- start configured session
DispatchRestartGame()         -- restart current session
DispatchResignGame()          -- surrender
DispatchQuitGame()            -- exit to menu
```

### GameOptions (setters)
```lua
options:SetAIDifficulty(OptionsAIDifficulty.HARD)
options:SetLocation(OptionsLocation.ARABIA)
options:SetMapSize(OptionsMapSize.TINY)
options:SetPopulation(200)
options:SetStartingAge(OptionsAge.DARK_AGE)
options:SetGameSpeed(1.5)
options:SetPlayersCount(2)
options:SetPlayerCivilization(0, OptionsCivilization.BRITONS)
```

### Settings (UI in CONTROL)
```lua
Settings.AddBool("My Toggle", true)
Settings.AddInt("Count", 5, 1, 100)
Settings.AddDropdown("Mode", "Fast", {"Fast", "Slow"})
Settings.GetBool("My Toggle", true)
```

### Game State (in Update/Init/Render)
```lua
GetAssignedPlayerId()
GetAssignedPlayer()           -- Player object
IsGamePaused()
IsMenuOpen()
```

## Headless Mode

```powershell
AoE2Control.exe --headless [--override-settings file] [--override-module file-or-folder]
```

- Outputs status lines to stdout: `Scanning...`, `Ready`, etc.
- Exit codes: 0=success, 1=already running, 2=bad args, 3=override failed, 4=startup failed
- AoE2:DE must be running before launch

## Updating the Module

To update the Lua code while CONTROL is running:
1. Edit `game/aoe2bot/aoe2bot.main.lua`
2. Re-run `.\scripts\launch.ps1` (or restart CONTROL headless)

Or copy manually and reassign in CONTROL UI:
```powershell
Copy-Item "game\aoe2bot\aoe2bot.main.lua" "$env:APPDATA\CONTROL\AoE2Control\modules\aoe2bot\aoe2bot.main.lua" -Force
```

## Key Constraints

- **Singleplayer only** — multiplayer disabled by AoE2Control
- **Windows only** — DLL injection + named pipes
- **Game commands in Update() only** — reads allowed in Init/Update/Render
- **One command per tick** by default (sequential execution)
- **Session control blocked during multithreading**

## Reference

Full API documentation: `tools/CONTROL_LUA_ENGINE_REFERENCE.md`
Official docs: https://aoe2control.github.io/
