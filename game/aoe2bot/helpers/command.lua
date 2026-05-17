local command = {}

local event_log = require("event_log")
local spatial = require("helpers.spatial")

-- ── Training ──

function command.train_vil()
    local ok, result = pcall(function()
        local tcs = GetAssignedPlayer():GetTownCenters()
        if #tcs == 0 then return false end
        return TrainUnit(tcs, UnitObjectType["VILLAGER_MALE"], 1)
    end)
    if ok and result then
        event_log.add("train villager")
    end
    return ok and result or false
end

-- ── Building ──

-- Place a building. Returns true if the command was accepted.
-- building_key: e.g. "HOUSE_DARK_AGE", "LUMBER_CAMP_DARK_AGE"
-- pos: Vector3 target position
-- builders: table of unit objects (optional, defaults to nearest idle vil)
function command.build(building_key, pos, builders)
    local typeId = UnitObjectType[building_key]
    if not typeId then
        Log("[cmd] Unknown building: " .. tostring(building_key))
        return false
    end
    if not builders or #builders == 0 then
        local query = require("helpers.query")
        local idle = query.idle_vils()
        if #idle > 0 then
            builders = { spatial.nearest(idle, pos) }
        else
            local vils = query.vils()
            if #vils > 0 then
                builders = { spatial.nearest(vils, pos) }
            end
        end
    end
    if not builders or #builders == 0 then return false end

    local ok, result = pcall(function()
        return UnitsBuildStructure(builders, typeId, pos)
    end)
    if ok and result then
        local ids = {}
        for _, b in ipairs(builders) do
            pcall(function() table.insert(ids, tostring(b:GetId())) end)
        end
        event_log.add("build " .. building_key .. " at " .. math.floor(pos.x) .. "," .. math.floor(pos.y)
            .. " with [" .. table.concat(ids, ",") .. "]")
    end
    return ok and result or false
end

-- Build near TC with auto-placement finding.
function command.build_near_tc(building_key, size, offset_x, offset_y)
    local query = require("helpers.query")
    local tc = query.tc_pos()
    if not tc then return false end
    local cx = tc.x + (offset_x or 0)
    local cy = tc.y + (offset_y or 0)
    local spot = spatial.find_placement(cx, cy, size or 2)
    if not spot then return false end
    return command.build(building_key, spot)
end

-- ── Gathering ──

-- Send units to gather from a target object (tree, sheep, gold, etc.)
function command.gather(units, target)
    if not units or #units == 0 or not target then return false end
    local ok, result = pcall(function()
        return UnitsTargetObject(units, target)
    end)
    return ok and result or false
end

-- ── Movement ──

function command.move(units, pos)
    if not units or #units == 0 or not pos then return false end
    local ok, result = pcall(function()
        return UnitsMove(units, pos)
    end)
    return ok and result or false
end

-- ── Scouting ──

function command.auto_scout(scout_unit)
    if not scout_unit then return false end
    local ok, result = pcall(function()
        return SetUnitStanceAutoScout({scout_unit})
    end)
    if ok then event_log.add("enable auto-scout") end
    return ok and result or false
end

-- ── Research ──

-- tech_id: numeric technology ID
-- label: human-readable name for event log
function command.research(tech_id, label)
    local ok, result = pcall(function()
        return ResearchTechnology(tech_id)
    end)
    if ok and result then
        event_log.add("research " .. (label or tostring(tech_id)))
    end
    return ok and result or false
end

-- ── Game Speed ──

function command.set_speed(multiplier)
    pcall(function() SetGameSpeedMultiplier(multiplier) end)
end

function command.pause()
    pcall(function() SetGamePaused(true) end)
end

function command.unpause()
    pcall(function() SetGamePaused(false) end)
end

return command
