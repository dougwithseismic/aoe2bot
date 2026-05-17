# AoE2Bot

A boilerplate for building an AoE2Control bot module that auto-starts a skirmish game and runs logic each tick.

## Prerequisites

- Windows 11
- Age of Empires II: Definitive Edition (installed and launchable)
- [AoE2Control](https://github.com/AoE2Control/AoE2Control/releases) — extract to `tools/AoE2Control/`

## Project Structure

```
aoe2bot/
├── game/aoe2bot/
│   └── aoe2bot.main.lua       # Bot module (session control + game loop)
├── scripts/
│   └── launch.ps1             # Headless launcher script
├── tools/
│   └── CONTROL_LUA_ENGINE_REFERENCE.md
└── CLAUDE.md
```

## Quick Start

1. Start Age of Empires II: DE (get to the main menu)
2. Run the launcher:

```powershell
.\scripts\launch.ps1
```

This uses `--headless` mode with `--override-module` to inject the bot module and start CONTROL without a GUI window.

3. The module auto-configures a 1v1 skirmish on Arabia and calls `DispatchStartGame()`.

## How It Works

| Lifecycle | What happens |
|-----------|-------------|
| `Load()` | Registers settings, configures game options, dispatches game start |
| `Init()` | Called when the match is ready — set up per-match state here |
| `Update()` | Called every tick — put your bot logic here |
| `End()` | Match ended — log result, clean up |

## Headless Mode

```powershell
AoE2Control.exe --headless --override-module "path/to/game/aoe2bot"
```

- `--headless`: No GUI, outputs status to stdout
- `--override-module <folder>`: Copies module into CONTROL's modules dir before startup
- Exit codes: 0=success, 1=already running, 2=bad args, 3=override failed, 4=startup failed

## Session Control API

```lua
local options = GetCurrentGameOptions()
options:SetAIDifficulty(OptionsAIDifficulty.HARD)
options:SetLocation(OptionsLocation.ARABIA)
options:SetMapSize(OptionsMapSize.TINY)
options:SetPopulation(200)
DispatchStartGame()
```

See `tools/CONTROL_LUA_ENGINE_REFERENCE.md` for the full API.

## Next Steps

Edit `game/aoe2bot/aoe2bot.main.lua` and add your logic in `Update()`. The module reloads when you re-run the launch script.
