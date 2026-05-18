---
name: launch-aoe2
description: Launch AoE2:DE from Steam, wait for it to be ready, then start AoE2Control in headless mode with the aoe2bot module for a skirmish match. Use when the user wants to start a bot game session.
---

# Launch AoE2:DE + AoE2Control Skill

Automates the full startup sequence for an aoe2bot session:
1. Launch AoE2:DE via Steam (app ID 813780)
2. Poll until the game process is running
3. Start AoE2Control in headless mode with the aoe2bot module

## Prerequisites

- Steam must be installed and logged in
- AoE2:DE must be owned on this Steam account
- `tools/AoE2Control/AoE2Control.exe` should exist (warn if missing but don't block game launch)

## Execution Steps

### Step 1: Check if AoE2:DE is already running

```powershell
$proc = Get-Process -Name "AoE2DE_s" -ErrorAction SilentlyContinue
if ($proc) {
    Write-Host "AoE2:DE is already running (PID $($proc.Id))"
} else {
    Write-Host "AoE2:DE is not running — will launch from Steam"
}
```

If the game is already running, skip to Step 3.

### Step 2: Launch AoE2:DE from Steam and wait for process

Launch via the Steam protocol URI, then poll for the process to appear.

```powershell
Start-Process "steam://rungameid/813780"
Write-Host "Launched AoE2:DE via Steam — waiting for process..."

$timeout = 120
$elapsed = 0
$interval = 5

while ($elapsed -lt $timeout) {
    Start-Sleep -Seconds $interval
    $elapsed += $interval
    $proc = Get-Process -Name "AoE2DE_s" -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "AoE2:DE process detected (PID $($proc.Id)) after ${elapsed}s"
        break
    }
    Write-Host "Waiting... (${elapsed}s / ${timeout}s)"
}

if (-not $proc) {
    Write-Error "AoE2:DE did not start within ${timeout}s — check Steam"
    exit 1
}
```

Once the process is detected, proceed immediately to AoE2Control — do NOT add a fixed sleep. If injection fails (exit code 4), retry after a few seconds rather than waiting upfront.

### Step 3: Launch AoE2Control headless with aoe2bot module

Check if AoE2Control exists. If missing, warn the user but don't abort (they may need to download it).

```powershell
$aoe2controlPath = "E:\WEB_PROJECTS\_CLIENTS\aoe2bot\tools\AoE2Control\AoE2Control.exe"
$modulePath = "E:\WEB_PROJECTS\_CLIENTS\aoe2bot\game\aoe2bot"

if (-not (Test-Path $aoe2controlPath)) {
    Write-Host "AoE2Control.exe not found at $aoe2controlPath"
    Write-Host "Download from https://github.com/AoE2Control/AoE2Control/releases and extract to tools/AoE2Control/"
    exit 1
}

Write-Host "Starting AoE2Control headless with module: $modulePath"
& $aoe2controlPath --headless --override-module $modulePath

$exitCode = $LASTEXITCODE
switch ($exitCode) {
    0 { Write-Host "AoE2Control injected — bot module loaded, skirmish starting." }
    1 { Write-Host "Another AoE2Control instance is already running." }
    2 { Write-Error "Invalid arguments passed to AoE2Control." }
    3 { Write-Error "Module override copy failed." }
    4 { Write-Error "Injection failed — game may not be ready yet. Wait a few seconds and retry." }
    default { Write-Host "AoE2Control exited with code: $exitCode" }
}
```

The aoe2bot module's `Load()` function auto-configures the skirmish: 1v1 Arabia, Tiny map, Hard AI, 200 pop, Dark Age start, 1.5x speed — then calls `DispatchStartGame()`.

## Error Recovery

- **Exit code 4**: Game wasn't ready for injection. Wait a few seconds and retry the AoE2Control command only (don't relaunch the game). If it keeps failing, ask the user to confirm the main menu is visible.
- **Exit code 1**: Another AoE2Control instance is running. Close it first or use the existing session.
- **Process not found**: Steam may need to update the game first. Ask the user to check Steam.
- **AoE2Control missing**: Tell the user to download it from the AoE2Control releases page and extract to `tools/AoE2Control/`.
