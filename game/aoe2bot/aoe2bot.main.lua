-- AoE2Bot — 22-Pop Scout Rush with overlay + event log
-- Auto-starts a skirmish, runs build order, renders HUD.

local overlay = require("overlay")
local event_log = require("event_log")
local build_order = require("build_order")

local TAG = "[AoE2Bot]"
local rt = nil

local DIFFICULTY_MAP = {
    Easiest = OptionsAIDifficulty.EASIEST,
    Standard = OptionsAIDifficulty.STANDARD,
    Moderate = OptionsAIDifficulty.MODERATE,
    Hard = OptionsAIDifficulty.HARD,
    Hardest = OptionsAIDifficulty.HARDEST,
    Extreme = OptionsAIDifficulty.EXTREME,
}

local LOCATION_MAP = {
    Arabia = OptionsLocation.ARABIA,
    Arena = OptionsLocation.ARENA,
    ["Black Forest"] = OptionsLocation.BLACK_FOREST,
    Nomad = OptionsLocation.NOMAD,
    Islands = OptionsLocation.ISLANDS,
}

function Load(playerId)
    Log(TAG .. " Loading for player " .. tostring(playerId))

    Settings.AddBool("Auto Start Game", true)
    Settings.AddBool("Show Overlay", true)
    Settings.AddBool("Run Build Order", true)
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

    local diff = Settings.GetString("Difficulty", "Hard")
    local map = Settings.GetString("Map", "Arabia")
    local pop = Settings.GetInt("Population Limit", 200)

    options:SetAIDifficulty(DIFFICULTY_MAP[diff] or OptionsAIDifficulty.HARD)
    options:SetLocation(LOCATION_MAP[map] or OptionsLocation.ARABIA)
    options:SetMapSize(OptionsMapSize.TINY)
    options:SetPopulation(pop)
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
    event_log.clear()
    event_log.add("Match started — 22 Pop Scout Rush")

    pcall(function()
        rt = ResourceTracker:new()
    end)

    build_order.init(rt)
    Log(TAG .. " Init — match ready, build order active")
end

function Update()
    if rt then pcall(function() rt:Update() end) end

    if Settings.GetBool("Run Build Order", true) then
        build_order.update(rt)
    end
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
