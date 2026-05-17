-- AoE2Bot — Boilerplate Module for AoE2Control
-- Auto-starts a skirmish game via Session Control, then runs bot logic each tick.

local TAG = "[AoE2Bot]"
local gameStarted = false
local tickCount = 0

function Load(playerId)
    Log(TAG .. " Loading for player " .. tostring(playerId))

    Settings.AddBool("Auto Start Game", true)
    Settings.AddDropdown("Difficulty", "Hard", { "Easiest", "Standard", "Moderate", "Hard", "Hardest", "Extreme" })
    Settings.AddDropdown("Map", "Arabia", { "Arabia", "Arena", "Black Forest", "Nomad", "Islands" })
    Settings.AddInt("Population Limit", 200, 25, 500)

    if Settings.GetBool("Auto Start Game", true) then
        configureAndStart()
    end
end

function configureAndStart()
    local options = GetCurrentGameOptions()
    if not options then
        Log(TAG .. " No GameOptions available (are you on the main menu?)")
        return
    end

    options:SetAIDifficulty(OptionsAIDifficulty.HARD)
    options:SetLocation(OptionsLocation.ARABIA)
    options:SetMapSize(OptionsMapSize.TINY)
    options:SetPopulation(200)
    options:SetStartingAge(OptionsAge.DARK_AGE)
    options:SetGameSpeed(1.5)
    options:SetPlayersCount(2)

    local ok = DispatchStartGame()
    if ok then
        Log(TAG .. " Game start dispatched")
    else
        Log(TAG .. " DispatchStartGame failed — may already be in game")
    end
end

function Init()
    gameStarted = true
    tickCount = 0
    Log(TAG .. " Match started — Init called")
end

function Update()
    tickCount = tickCount + 1

    -- Your bot logic goes here.
    -- This runs every update tick (~configured interval in settings.ini).
    -- Example: log every 100 ticks
    if tickCount % 100 == 0 then
        Log(TAG .. " Tick " .. tostring(tickCount))
    end
end

function Render()
    -- Optional: draw overlays each frame
end

function End(hasWon)
    if hasWon then
        Log(TAG .. " Victory!")
    else
        Log(TAG .. " Defeat or game ended")
    end
    gameStarted = false
end

function Unload()
    Log(TAG .. " Unloaded")
end
