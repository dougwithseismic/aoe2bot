# Launch AoE2Control in headless mode with the aoe2bot module.
# Prerequisites: Age of Empires II: DE must already be running.

param(
    [string]$AoE2ControlPath = "E:\WEB_PROJECTS\_CLIENTS\aoe2bot\tools\AoE2Control\AoE2Control.exe",
    [string]$ModulePath = "E:\WEB_PROJECTS\_CLIENTS\aoe2bot\game\aoe2bot"
)

if (-not (Test-Path $AoE2ControlPath)) {
    Write-Error "AoE2Control.exe not found at: $AoE2ControlPath"
    Write-Host "Download it from https://github.com/AoE2Control/AoE2Control/releases and extract to tools/AoE2Control/"
    exit 1
}

if (-not (Test-Path $ModulePath)) {
    Write-Error "Module not found at: $ModulePath"
    exit 1
}

Write-Host "Launching AoE2Control headless with module: $ModulePath"
Write-Host "---"

& $AoE2ControlPath --headless --override-module $ModulePath

$exitCode = $LASTEXITCODE
switch ($exitCode) {
    0 { Write-Host "`nSuccess — CONTROL is ready." }
    1 { Write-Host "`nAnother CONTROL instance is already running." }
    2 { Write-Error "Invalid arguments." }
    3 { Write-Error "Override copy failed." }
    4 { Write-Error "Startup failed — is AoE2:DE running?" }
    default { Write-Host "`nExited with code: $exitCode" }
}

exit $exitCode
