-- AoE2Bot — 22-Pop Scout Rush with overlay + event log
local TAG = "[AoE2Bot]"
local rt = nil
local event_log = require("event_log")
local overlay = require("overlay")
local h = require("helpers")
local build_order = require("build_order")

function Load(playerId)
    Log(TAG .. " Load player " .. tostring(playerId))
    Settings.AddBool("Show Overlay", true)
    Settings.AddBool("Run Build Order", true)

    local options = GetCurrentGameOptions()
    if options then
        pcall(function() options:SetAIDifficulty(OptionsAIDifficulty.HARD) end)
        pcall(function() options:SetLocation(OptionsLocation.ARABIA) end)
        pcall(function() options:SetMapSize(OptionsMapSize.TINY) end)
        pcall(function() options:SetPopulation(200) end)
        pcall(function() options:SetStartingAge(OptionsAge.DARK_AGE) end)
        pcall(function() options:SetGameSpeed(10) end)
        pcall(function() options:SetPlayersCount(2) end)
        local ok = DispatchStartGame()
        if ok then Log(TAG .. " Game dispatched") else Log(TAG .. " DispatchStartGame false (already in game?)") end
    end
end

function Init()
    Log(TAG .. " Init")
    event_log.clear()
    event_log.add("Match started — 22 Pop Scout Rush")
    pcall(function()
        rt = ResourceTracker:new()
        Log(TAG .. " ResourceTracker OK")
    end)
    h.init_construction(rt)
    build_order.init(rt)
    Log(TAG .. " Build order active")
end

function Update()
    if rt then pcall(function() rt:Update() end) end
    h.update_construction()
    if Settings.GetBool("Run Build Order", true) then
        local ok, err = pcall(function() build_order.update(rt) end)
        if not ok then Log(TAG .. " ERR: " .. tostring(err)) end
    end
end

function Render()
    if Settings.GetBool("Show Overlay", true) then
        local ok, err = pcall(function() overlay.render() end)
        if not ok then Log(TAG .. " Render ERR: " .. tostring(err)) end
    end
end

function End(hasWon)
    event_log.add(hasWon and "VICTORY" or "Defeat")
    Log(TAG .. " End")
end
