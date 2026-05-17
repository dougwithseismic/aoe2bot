-- AoE2Bot — Module with game state overlay + event log
-- Auto-starts a skirmish, renders HUD overlay, logs actions.

local overlay = require("overlay")
local event_log = require("event_log")

local TAG = "[AoE2Bot]"
local tickCount = 0

function Load(playerId)
    Log(TAG .. " Loading for player " .. tostring(playerId))

    Settings.AddBool("Auto Start Game", true)
    Settings.AddBool("Show Overlay", true)
    Settings.AddBool("Show Event Log", true)
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
    tickCount = 0
    event_log.clear()
    event_log.add("Match started")
    Log(TAG .. " Init — match ready")
end

function Update()
    tickCount = tickCount + 1

    -- Your bot logic goes here.
    -- Use event_log.add() to log actions:
    --   event_log.add("place barracks at 45,60 with 4 vils [12,13,14,15]")
    --   event_log.add("train villager from TC")
    --   event_log.add("advance to Feudal Age")
end

function Render()
    if Settings.GetBool("Show Overlay", true) then
        overlay.render()
    end
end

function End(hasWon)
    if hasWon then
        event_log.add("VICTORY")
    else
        event_log.add("Defeat / game ended")
    end
end

function Unload()
    Log(TAG .. " Unloaded")
end
