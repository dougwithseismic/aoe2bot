-- helpers.lua — All query, spatial, and command utilities in one flat file.
-- Each function wraps ONE pcall at the boundary, returns sensible defaults on failure.

local helpers = {}
local event_log = require("event_log")

-- ══ Error Tracking ══

local errors = {}
local MAX_ERRORS = 20
local last_err = ""

function helpers.try(label, fn)
    local ok, result = pcall(fn)
    if not ok then
        local msg = tostring(result)
        if msg ~= last_err then
            last_err = msg
            local entry = "[ERR:" .. label .. "] " .. msg
            Log(entry)
            table.insert(errors, 1, entry)
            if #errors > MAX_ERRORS then table.remove(errors, #errors) end
        end
    end
    return ok, result
end

function helpers.get(label, fn, default)
    local ok, result = helpers.try(label, fn)
    if ok then return result end
    return default
end

function helpers.get_errors() return errors end

-- ══ Queries ══

function helpers.player()
    return GetAssignedPlayer()
end

function helpers.vils()
    return helpers.get("vils", function()
        local p = GetAssignedPlayer()
        local all = p:GetObjectsByClass(UnitClass.VILLAGER)
        local pid = p:GetId()
        local out = {}
        for _, v in ipairs(all) do
            if v:IsAlive() and v:GetOwningPlayer():GetId() == pid then
                table.insert(out, v)
            end
        end
        return out
    end, {})
end

function helpers.idle_vils()
    return helpers.get("idle_vils", function()
        local p = GetAssignedPlayer()
        local all = p:GetObjectsByClass(UnitClass.VILLAGER)
        local pid = p:GetId()
        local out = {}
        for _, v in ipairs(all) do
            if v:IsAlive() and v:IsIdle() and v:GetOwningPlayer():GetId() == pid then
                table.insert(out, v)
            end
        end
        return out
    end, {})
end

function helpers.scout()
    return helpers.get("scout", function()
        local p = GetAssignedPlayer()
        -- Try class 961 (scout cavalry)
        local byClass = p:GetObjectsByClass(961)
        if byClass then
            for _, u in ipairs(byClass) do
                if u:IsAlive() then return u end
            end
        end
        -- Fallback: find by name
        for _, u in ipairs(p:GetPlayerObjects()) do
            if u:IsAlive() then
                local name = string.upper(u:GetName() or "")
                if string.find(name, "SCOUT") and not string.find(name, "SCOUTING") then
                    return u
                end
            end
        end
        return nil
    end, nil)
end

function helpers.tcs()
    return helpers.get("tcs", function() return GetAssignedPlayer():GetTownCenters() end, {})
end

function helpers.tc_pos()
    local tcs = helpers.tcs()
    if #tcs > 0 then
        return helpers.get("tc_pos", function() return tcs[1]:GetPosition() end, nil)
    end
    return nil
end

function helpers.pop()
    return helpers.get("pop", function()
        local current = GetFact(Fact.POPULATION) or 0
        -- Count housing from buildings: TC=5, House=5
        local p = GetAssignedPlayer()
        local tcs = p:GetTownCenters()
        local houses = 0
        for _, o in ipairs(p:GetPlayerObjects()) do
            if o:IsAlive() and string.find(string.upper(o:GetName() or ""), "HOUSE") then
                houses = houses + 1
            end
        end
        local housing = #tcs * 5 + houses * 5
        local headroom = housing - current
        local vilCount = 0
        if Fact.VILLAGER_COUNT then vilCount = GetFact(Fact.VILLAGER_COUNT) or 0 end
        if vilCount == 0 then vilCount = #helpers.vils() end
        return {
            current = current,
            headroom = headroom,
            housing = housing,
            vils = vilCount,
        }
    end, { current = 0, headroom = 0, housing = 0, vils = 0 })
end

function helpers.resources()
    return helpers.get("resources", function()
        return {
            food = GetFact(Fact.FOOD_AMOUNT) or 0,
            wood = GetFact(Fact.WOOD_AMOUNT) or 0,
            gold = GetFact(Fact.GOLD_AMOUNT) or 0,
            stone = GetFact(Fact.STONE_AMOUNT) or 0,
        }
    end, { food = 0, wood = 0, gold = 0, stone = 0 })
end

function helpers.can_afford(food, wood, gold, stone)
    local r = helpers.resources()
    return r.food >= (food or 0) and r.wood >= (wood or 0)
        and r.gold >= (gold or 0) and r.stone >= (stone or 0)
end

function helpers.age()
    if not Fact.CURRENT_AGE then return 0 end
    return helpers.get("age", function() return GetFact(Fact.CURRENT_AGE) end, 0)
end

function helpers.is_researched(tech_id)
    return helpers.get("is_researched", function() return IsTechnologyResearched(tech_id) end, false)
end

function helpers.can_research(tech_id)
    return helpers.get("can_research", function() return CanResearch(tech_id) end, false)
end

function helpers.buildings(name_pattern)
    return helpers.get("buildings", function()
        local p = GetAssignedPlayer()
        local all = p:GetPlayerObjects()
        local out = {}
        for _, o in ipairs(all) do
            if o:IsAlive() then
                local name = string.upper(o:GetName() or "")
                if string.find(name, name_pattern) then table.insert(out, o) end
            end
        end
        return out
    end, {})
end

-- ══ Spatial ══

function helpers.dist(a, b)
    local dx, dy = a.x - b.x, a.y - b.y
    return math.sqrt(dx * dx + dy * dy)
end

function helpers.nearest(objects, pos)
    if not objects or #objects == 0 then return nil, math.huge end
    local best, bestDist = nil, math.huge
    for _, obj in ipairs(objects) do
        local ok, opos = pcall(function() return obj:GetPosition() end)
        if ok and opos then
            local d = helpers.dist(opos, pos)
            if d < bestDist then best = obj; bestDist = d end
        end
    end
    return best, bestDist
end

function helpers.is_footprint_clear(cx, cy, size)
    local ok, result = helpers.try("footprint", function()
        local half = math.floor(size / 2)
        for dx = -half, half - 1 do
            for dy = -half, half - 1 do
                local tile = GetMapTile(math.floor(cx) + dx, math.floor(cy) + dy)
                if not tile then return false end
                if not tile:IsBuildable() or not tile:IsWalkable() then return false end
                if tile:GetObjectCount() > 0 then
                    for _, obj in ipairs(tile:GetObjects()) do
                        local cls = obj:GetClass()
                        if cls ~= 904 and cls ~= 961 and cls ~= 958 then return false end
                    end
                end
            end
        end
        return true
    end)
    return ok and result or false
end

function helpers.find_placement(cx, cy, size)
    for r = 0, 10, 2 do
        for _, off in ipairs({{r,0},{-r,0},{0,r},{0,-r},{r,r},{-r,r},{r,-r},{-r,-r}}) do
            if helpers.is_footprint_clear(cx + off[1], cy + off[2], size) then
                return Vector2(cx + off[1], cy + off[2])
            end
        end
    end
    return nil
end

function helpers.find_safe_trees(rt, tc_pos)
    if not rt or not tc_pos then return nil end
    return helpers.get("find_trees", function()
        local trees = rt:GetTrees()
        local near = {}
        for _, t in ipairs(trees) do
            if helpers.dist(t:GetPosition(), tc_pos) < 20 then table.insert(near, t) end
        end
        if #near == 0 then return nil end
        local mapW, mapH = GetMapWidth(), GetMapHeight()
        local safeX, safeY = tc_pos.x - mapW / 2, tc_pos.y - mapH / 2
        table.sort(near, function(a, b)
            local pa, pb = a:GetPosition(), b:GetPosition()
            return (pa.x - tc_pos.x) * safeX + (pa.y - tc_pos.y) * safeY >
                   (pb.x - tc_pos.x) * safeX + (pb.y - tc_pos.y) * safeY
        end)
        return near[1]
    end, nil)
end

function helpers.find_food(rt, tc_pos)
    if not rt or not tc_pos then return nil end
    return helpers.get("find_food", function()
        local owned = rt:GetOwnedLivestock()
        if owned then
            local near = {}
            for _, o in ipairs(owned) do
                if helpers.dist(o:GetPosition(), tc_pos) < 15 then table.insert(near, o) end
            end
            if #near > 0 then return helpers.nearest(near, tc_pos) end
        end
        local forage = rt:GetForage()
        if forage then
            local best, d = helpers.nearest(forage, tc_pos)
            if best and d < 20 then return best end
        end
        return nil
    end, nil)
end

function helpers.find_gold(rt, tc_pos)
    if not rt or not tc_pos then return nil end
    return helpers.get("find_gold", function()
        return helpers.nearest(rt:GetGold(), tc_pos)
    end, nil)
end

-- ══ Construction ══

local construction = nil

function helpers.init_construction()
    helpers.get("init_construction", function()
        construction = ConstructionPlacement:new()
        Log("[helpers] ConstructionPlacement OK")
    end, nil)
end

function helpers.get_construction()
    return construction
end

-- ══ Commands ══

function helpers.train_vil()
    local typeId = UnitObjectType["VILLAGER_MALE"]
    if not typeId then
        Log("[helpers] VILLAGER_MALE not found in UnitObjectType")
        return false
    end
    local result = helpers.get("train_vil", function()
        return TrainUnit(typeId)
    end, false)
    if result then event_log.add("train villager") end
    return result
end

function helpers.build(building_key, pos, builders)
    if not construction then return false end
    local typeId = UnitObjectType[building_key]
    if not typeId then
        Log("[helpers] " .. building_key .. " not found in UnitObjectType")
        return false
    end
    if not pos then return false end
    local result = helpers.get("build:" .. building_key, function()
        return construction:BuildStructure(typeId, pos, 0, 1)
    end, false)
    if result then
        event_log.add("build " .. building_key .. " at " .. math.floor(pos.x) .. "," .. math.floor(pos.y))
    end
    return result
end

function helpers.build_near_tc(building_key, size, ox, oy)
    if not construction then return false end
    local typeId = UnitObjectType[building_key]
    if not typeId then
        Log("[helpers] " .. building_key .. " not found in UnitObjectType")
        return false
    end
    local result = helpers.get("build_tc:" .. building_key, function()
        return construction:BuildStructureAtTown(typeId, 1)
    end, false)
    if result then
        event_log.add("build " .. building_key .. " near TC")
    end
    return result
end

function helpers.gather(units, target)
    if not units or #units == 0 or not target then return false end
    if not units[1] then return false end
    return helpers.get("gather", function() return UnitsTargetObject(units, target) end, false)
end

function helpers.move(units, pos)
    if not units or #units == 0 or not pos then return false end
    return helpers.get("move", function() return UnitsMove(units, pos) end, false)
end

function helpers.auto_scout(scout_unit)
    -- Use built-in EnableScouting() which auto-finds the scout unit
    local result = helpers.get("auto_scout", function() return EnableScouting() end, false)
    if result then event_log.add("enable auto-scout") end
    return result
end

function helpers.research(tech_id, label)
    local result = helpers.get("research:" .. tostring(tech_id), function()
        return ResearchTechnology(tech_id)
    end, false)
    if result then event_log.add("research " .. (label or tostring(tech_id))) end
    return result
end

return helpers
