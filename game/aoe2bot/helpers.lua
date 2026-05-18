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
        local byClass = p:GetObjectsByClass(961)
        if byClass then
            for _, u in ipairs(byClass) do
                if u:IsAlive() then return u end
            end
        end
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
        local vilCount = 0
        if Fact.VILLAGER_COUNT then vilCount = GetFact(Fact.VILLAGER_COUNT) or 0 end
        if vilCount == 0 then vilCount = #helpers.vils() end
        return { current = current, vils = vilCount }
    end, { current = 0, vils = 0 })
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
                        if obj:IsVisible() then
                            local cls = obj:GetClass()
                            if cls ~= 904 and cls ~= 961 and cls ~= 958 then return false end
                        end
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

function helpers.find_tree_cluster(rt, tc_pos)
    if not rt or not tc_pos then return nil end
    return helpers.get("tree_cluster", function()
        local trees = rt:GetTrees()
        if not trees or #trees == 0 then return nil end
        local mapW, mapH = GetMapWidth(), GetMapHeight()
        local cx, cy = mapW / 2, mapH / 2
        local safeX, safeY = tc_pos.x - cx, tc_pos.y - cy
        local safeLen = math.sqrt(safeX * safeX + safeY * safeY)
        if safeLen > 0 then safeX, safeY = safeX / safeLen, safeY / safeLen end

        local candidates = {}
        for _, t in ipairs(trees) do
            local p = t:GetPosition()
            local d = helpers.dist(p, tc_pos)
            if d > 4 and d < 30 then
                local dx, dy = p.x - tc_pos.x, p.y - tc_pos.y
                local dot = dx * safeX + dy * safeY
                if dot > 0 then
                    table.insert(candidates, p)
                end
            end
        end
        if #candidates == 0 then
            for _, t in ipairs(trees) do
                local p = t:GetPosition()
                if helpers.dist(p, tc_pos) < 30 then
                    table.insert(candidates, p)
                end
            end
        end
        if #candidates == 0 then return nil end

        local bestPos, bestCount = nil, 0
        for _, p in ipairs(candidates) do
            local count = 0
            for _, q in ipairs(candidates) do
                if helpers.dist(p, q) < 6 then count = count + 1 end
            end
            if count > bestCount then bestCount = count; bestPos = p end
        end
        return bestPos
    end, nil)
end

function helpers.find_berry_pos(rt, tc_pos)
    if not rt or not tc_pos then return nil end
    return helpers.get("berry_pos", function()
        local forage = rt:GetForage()
        if not forage or #forage == 0 then return nil end
        local near = {}
        for _, f in ipairs(forage) do
            local p = f:GetPosition()
            if helpers.dist(p, tc_pos) < 30 then table.insert(near, p) end
        end
        if #near == 0 then return nil end
        local sx, sy = 0, 0
        for _, p in ipairs(near) do sx = sx + p.x; sy = sy + p.y end
        return Vector2(sx / #near, sy / #near)
    end, nil)
end

local function find_resource_cluster(label, getter, tc_pos)
    if not tc_pos then return nil end
    return helpers.get(label, function()
        local resources = getter()
        if not resources or #resources == 0 then return nil end
        local best, bestDist = nil, math.huge
        for _, r in ipairs(resources) do
            local p = r:GetPosition()
            local d = helpers.dist(p, tc_pos)
            if d < bestDist then best = p; bestDist = d end
        end
        if not best then return nil end
        local sx, sy, n = 0, 0, 0
        for _, r in ipairs(resources) do
            local p = r:GetPosition()
            if helpers.dist(p, best) < 6 then
                sx = sx + p.x; sy = sy + p.y; n = n + 1
            end
        end
        if n == 0 then return best end
        return Vector2(sx / n, sy / n)
    end, nil)
end

function helpers.find_gold_pos(rt, tc_pos)
    if not rt then return nil end
    return find_resource_cluster("gold_pos", function() return rt:GetGold() end, tc_pos)
end

function helpers.find_stone_pos(rt, tc_pos)
    if not rt then return nil end
    return find_resource_cluster("stone_pos", function() return rt:GetStone() end, tc_pos)
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
            if best and d < 30 then return best end
        end
        local farms = rt:GetFarms()
        if farms then
            local best, d = helpers.nearest(farms, tc_pos)
            if best then return best end
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

function helpers.lc_pos()
    local lcs = helpers.buildings("LUMBER")
    if #lcs > 0 then
        return helpers.get("lc_pos", function() return lcs[1]:GetPosition() end, nil)
    end
    return nil
end

function helpers.find_trees_near_lc(rt)
    local lc = helpers.lc_pos()
    if not rt or not lc then return nil end
    return helpers.get("trees_near_lc", function()
        local trees = rt:GetTrees()
        if not trees or #trees == 0 then return nil end
        local best, bestDist = nil, math.huge
        for _, t in ipairs(trees) do
            local d = helpers.dist(t:GetPosition(), lc)
            if d < 15 and d < bestDist then best = t; bestDist = d end
        end
        return best
    end, nil)
end

function helpers.farm_count(rt)
    if not rt then return 0 end
    return helpers.get("farm_count", function()
        local farms = rt:GetFarms()
        if not farms then return 0 end
        return #farms
    end, 0)
end

-- ══ Construction ══

local construction = nil
local vilOccupation = nil

function helpers.init_construction(resource_tracker)
    helpers.get("init_construction", function()
        if resource_tracker then
            vilOccupation = VillagerOccupation:new(resource_tracker)
            Log("[helpers] VillagerOccupation OK")
            construction = ConstructionPlacement:new(vilOccupation)
        else
            construction = ConstructionPlacement:new(nil)
        end
        Log("[helpers] ConstructionPlacement OK")
    end, nil)
end

function helpers.get_construction()
    return construction
end

function helpers.update_construction()
    if construction then pcall(function() construction:Update() end) end
end

-- ══ Commands ══

local function resolve_type_id(building_key)
    local typeId = UnitObjectType[building_key]
    if typeId then return typeId end
    local base = string.gsub(building_key, "_DARK_AGE", "")
    base = string.gsub(base, "_FEUDAL_AGE", "")
    base = string.gsub(base, "_CASTLE_AGE", "")
    return UnitObjectType[base]
end

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

function helpers.build_at(building_key, target_pos)
    local typeId = resolve_type_id(building_key)
    if not typeId then
        Log("[helpers] " .. building_key .. " not found")
        return false
    end
    local vils = helpers.idle_vils()
    if #vils == 0 then
        vils = helpers.vils()
        if #vils == 0 then return false end
    end
    local tp = Vector2(target_pos.x, target_pos.y)
    local result = helpers.get("build_at:" .. building_key, function()
        return UnitsBuildStructure({vils[1]}, typeId, tp)
    end, false)
    if result then
        event_log.add("build " .. building_key .. " at resource")
    end
    return result
end

function helpers.build_near_tc(building_key)
    if not construction then return false end
    local typeId = resolve_type_id(building_key)
    if not typeId then
        Log("[helpers] " .. building_key .. " not found")
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

function helpers.build_farm()
    if not construction then return false end
    local typeId = UnitObjectType["FARM"]
    if not typeId then return false end
    local result = helpers.get("build_farm", function()
        return construction:BuildStructureAtTown(typeId, 1)
    end, false)
    if result then event_log.add("build FARM") end
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

function helpers.auto_scout()
    return helpers.get("auto_scout", function()
        local scout = helpers.scout()
        if not scout then return false end
        SetUnitStanceAutoScout({scout})
        event_log.add("auto-scout enabled")
        return true
    end, false)
end

function helpers.research(tech_id, label)
    local result = helpers.get("research:" .. tostring(tech_id), function()
        return ResearchTechnology(tech_id)
    end, false)
    if result then event_log.add("research " .. (label or tostring(tech_id))) end
    return result
end

return helpers
