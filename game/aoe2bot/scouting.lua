-- scouting.lua — Manual scout patrol around TC before enabling auto-scout.
-- Generates waypoints in a ring around TC, prioritizing the safe side (away
-- from map center / toward the map edge). Once key resources are discovered
-- or all waypoints are visited, switches the scout to auto-scout mode.

local event_log = require("event_log")

local scouting = {}

-- ══ State ══

local state = {
    initialized = false,
    done = false,
    waypoints = {},
    current_wp = 1,
    tc_pos = nil,
    move_issued = false,  -- whether we issued a move for the current waypoint
    tick = 0,
    found = {
        trees = false,
        berries = false,
        gold = false,
        stone = false,
        huntables = false,
    },
}

-- ══ Waypoint Generation ══

-- Build waypoints: 8 points in a ring at inner_radius (clockwise from safe
-- direction), then 2-3 points at outer_radius on the safe side only.
local function generate_waypoints(tc_pos)
    local waypoints = {}

    -- Determine safe direction: away from map center = toward our map edge
    local mapW, mapH = 0, 0
    local ok1, mw = pcall(GetMapWidth)
    local ok2, mh = pcall(GetMapHeight)
    if ok1 then mapW = mw end
    if ok2 then mapH = mh end

    -- Fallback if map size unavailable
    if mapW == 0 then mapW = 200 end
    if mapH == 0 then mapH = 200 end

    local cx, cy = mapW / 2, mapH / 2
    -- Safe direction = TC position minus map center (points away from center)
    local dx = tc_pos.x - cx
    local dy = tc_pos.y - cy
    local len = math.sqrt(dx * dx + dy * dy)
    if len < 1 then
        -- TC is dead center (unlikely), pick arbitrary direction
        dx, dy = 1, 0
        len = 1
    end
    -- Normalize to unit vector
    local safeDirX = dx / len
    local safeDirY = dy / len

    -- Starting angle = angle of safe direction
    local startAngle = math.atan2(safeDirY, safeDirX)

    -- Inner ring: 8 waypoints at radius ~22, going clockwise from safe direction
    local INNER_RADIUS = 22
    for i = 0, 7 do
        local angle = startAngle + (i * 2 * math.pi / 8)
        local wx = tc_pos.x + INNER_RADIUS * math.cos(angle)
        local wy = tc_pos.y + INNER_RADIUS * math.sin(angle)
        -- Clamp to map bounds with a small margin
        wx = math.max(2, math.min(mapW - 2, wx))
        wy = math.max(2, math.min(mapH - 2, wy))
        table.insert(waypoints, { x = wx, y = wy })
    end

    -- Outer ring: 3 waypoints at radius ~35, on the safe side only
    -- These cover the area further from TC toward our map edge where
    -- resources like distant gold or stone might be.
    local OUTER_RADIUS = 35
    local outerAngles = { startAngle - 0.5, startAngle, startAngle + 0.5 }
    for _, angle in ipairs(outerAngles) do
        local wx = tc_pos.x + OUTER_RADIUS * math.cos(angle)
        local wy = tc_pos.y + OUTER_RADIUS * math.sin(angle)
        wx = math.max(2, math.min(mapW - 2, wx))
        wy = math.max(2, math.min(mapH - 2, wy))
        table.insert(waypoints, { x = wx, y = wy })
    end

    return waypoints
end

-- ══ Scout Finder ══

local function find_scout()
    local ok, scout = pcall(function()
        local p = GetAssignedPlayer()
        -- Try class 961 (scout cavalry)
        local byClass = p:GetObjectsByClass(961)
        if byClass then
            for _, u in ipairs(byClass) do
                if u:IsAlive() then return u end
            end
        end
        -- Fallback: search by name
        for _, u in ipairs(p:GetPlayerObjects()) do
            if u:IsAlive() then
                local name = string.upper(u:GetName() or "")
                if string.find(name, "SCOUT") and not string.find(name, "SCOUTING") then
                    return u
                end
            end
        end
        return nil
    end)
    if ok then return scout end
    return nil
end

-- ══ Resource Discovery Check ══

local function check_resources(rt)
    if not rt then return end

    if not state.found.trees then
        local ok, trees = pcall(function() return rt:GetTrees() end)
        if ok and trees and #trees > 0 then
            state.found.trees = true
            Log("[Scout] discovered trees (" .. #trees .. " visible)")
        end
    end

    if not state.found.berries then
        local ok, forage = pcall(function() return rt:GetForage() end)
        if ok and forage and #forage > 0 then
            state.found.berries = true
            event_log.add("Scout found berries")
            Log("[Scout] discovered berries (" .. #forage .. " bushes)")
        end
    end

    if not state.found.gold then
        local ok, gold = pcall(function() return rt:GetGold() end)
        if ok and gold and #gold > 0 then
            state.found.gold = true
            event_log.add("Scout found gold")
            Log("[Scout] discovered gold (" .. #gold .. " tiles)")
        end
    end

    if not state.found.stone then
        local ok, stone = pcall(function() return rt:GetStone() end)
        if ok and stone and #stone > 0 then
            state.found.stone = true
            event_log.add("Scout found stone")
            Log("[Scout] discovered stone (" .. #stone .. " tiles)")
        end
    end

    if not state.found.huntables and state.tc_pos then
        local ok, hunt = pcall(function()
            return rt:GetConvertibleLivestock(state.tc_pos, 30)
        end)
        if ok and hunt and #hunt > 0 then
            state.found.huntables = true
            event_log.add("Scout found huntables")
            Log("[Scout] discovered huntables (" .. #hunt .. " animals)")
        end
    end
end

local function all_key_resources_found()
    return state.found.trees and state.found.berries
        and state.found.gold and state.found.stone
end

-- ══ Distance Helper ══

local function dist(a, b)
    local dx = a.x - b.x
    local dy = a.y - b.y
    return math.sqrt(dx * dx + dy * dy)
end

-- ══ Enable Auto-Scout ══

local function enable_auto_scout(scout)
    local ok = pcall(function()
        SetUnitStanceAutoScout({ scout })
    end)
    if ok then
        event_log.add("Manual scout done -> auto-scout")
        Log("[Scout] switched to auto-scout")
    else
        Log("[Scout] WARN: failed to set auto-scout stance")
    end
end

-- ══ Public API ══

function scouting.init(resource_tracker, tc_pos)
    if not tc_pos then
        Log("[Scout] init failed: no TC position")
        return
    end

    state = {
        initialized = true,
        done = false,
        waypoints = {},
        current_wp = 1,
        tc_pos = tc_pos,
        move_issued = false,
        tick = 0,
        found = {
            trees = false,
            berries = false,
            gold = false,
            stone = false,
            huntables = false,
        },
    }

    local ok, wps = pcall(generate_waypoints, tc_pos)
    if ok and wps then
        state.waypoints = wps
        event_log.add("Scout patrol: " .. #wps .. " waypoints")
        Log("[Scout] init OK — " .. #wps .. " waypoints, TC at "
            .. string.format("%.0f,%.0f", tc_pos.x, tc_pos.y))
    else
        Log("[Scout] WARN: waypoint generation failed, will auto-scout immediately")
        state.done = true
    end
end

function scouting.update(resource_tracker)
    if state.done or not state.initialized then return end
    state.tick = state.tick + 1

    -- Check resource discovery each tick
    check_resources(resource_tracker)

    -- Early completion: all key resources found
    if all_key_resources_found() then
        Log("[Scout] all key resources found — ending manual scout early")
        event_log.add("All resources found, ending patrol")
        local scout = find_scout()
        if scout then enable_auto_scout(scout) end
        state.done = true
        return
    end

    -- All waypoints visited
    if state.current_wp > #state.waypoints then
        Log("[Scout] all waypoints visited — ending manual scout")
        event_log.add("Patrol complete")
        local scout = find_scout()
        if scout then enable_auto_scout(scout) end
        state.done = true
        return
    end

    -- Find the scout unit
    local scout = find_scout()
    if not scout then return end

    -- Get scout position
    local ok, scout_pos = pcall(function() return scout:GetPosition() end)
    if not ok or not scout_pos then return end

    local wp = state.waypoints[state.current_wp]
    local d = dist(scout_pos, wp)

    -- Within 4 tiles of waypoint: advance to next
    if d < 4 then
        state.current_wp = state.current_wp + 1
        state.move_issued = false

        if state.current_wp > #state.waypoints then
            -- Will be caught next tick at the top
            return
        end
        -- Issue move to the next waypoint immediately
        wp = state.waypoints[state.current_wp]
        pcall(function()
            UnitsMove({ scout }, Vector2(wp.x, wp.y))
        end)
        state.move_issued = true
        return
    end

    -- If scout is idle or we haven't issued a move yet, send it to current waypoint
    local idle = false
    local ok_idle, is_idle = pcall(function() return scout:IsIdle() end)
    if ok_idle then idle = is_idle end

    if idle or not state.move_issued then
        pcall(function()
            UnitsMove({ scout }, Vector2(wp.x, wp.y))
        end)
        state.move_issued = true
    end
end

function scouting.is_done()
    return state.done
end

return scouting
