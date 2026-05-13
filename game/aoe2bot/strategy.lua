-- Fast Castle 27+2 Build Order
-- Runs autonomously from Update() — no Python bridge needed.
--
-- Build order:
--   1-6:  food (sheep)      7-10: wood (LC at 8)
--   11-18: food (mill at 12, berries/farms)
--   19-23: wood             24-26: gold (MC at 24)
--   Loom at 24, Feudal at 500f + 2 dark buildings
--   Feudal: blacksmith + market → Castle
--   Castle: 2nd TC, boom

local strategy = {}

local state = {
    tick = 0,
    scoutId = nil,
    scoutWaypoint = 0,
    scoutDone = false,
    tcBuilt = false,
    tcFoodForced = false,
    woodTarget = nil,
    built = {},
    houseCd = 0,
    farmCd = 0,
    feudalClicked = false,
    castleClicked = false,
    lastVilCount = 0,
}

strategy.resourceTracker = nil

-- ── Helpers ──

local function getPlayer()
    return GetAssignedPlayer()
end

local function getVils()
    local p = getPlayer()
    if not p then return {} end
    local vils = {}
    pcall(function()
        for _, v in ipairs(p:GetObjectsByClass(UnitClass.VILLAGER)) do
            if v:IsAlive() and v:GetOwningPlayer():GetId() == p:GetId() then
                table.insert(vils, v)
            end
        end
    end)
    return vils
end

local function getIdleVils()
    local idle = {}
    for _, v in ipairs(getVils()) do
        if v:IsIdle() then table.insert(idle, v) end
    end
    return idle
end

local function getTcs()
    local tcs = {}
    pcall(function() tcs = getPlayer():GetTownCenters() end)
    return tcs
end

local function getTcPos()
    local tcs = getTcs()
    if #tcs > 0 then return tcs[1]:GetPosition() end
    return nil
end

local function getVilCenter()
    local vils = getVils()
    if #vils == 0 then return nil end
    local sx, sy = 0, 0
    for _, v in ipairs(vils) do
        local p = v:GetPosition()
        sx = sx + p.x; sy = sy + p.y
    end
    return Vector3(sx / #vils, sy / #vils, 0)
end

local function dist(a, b)
    local dx, dy = a.x - b.x, a.y - b.y
    return math.sqrt(dx*dx + dy*dy)
end

local function getResources()
    local r = { food = 0, wood = 0, gold = 0, stone = 0 }
    pcall(function()
        r.food = GetFact(Fact.FOOD_AMOUNT)
        r.wood = GetFact(Fact.WOOD_AMOUNT)
        r.gold = GetFact(Fact.GOLD_AMOUNT)
        r.stone = GetFact(Fact.STONE_AMOUNT)
    end)
    return r
end

local function getAge()
    local age = 0
    pcall(function() age = GetFact(Fact.CURRENT_AGE) end)
    return age
end

local function getPopInfo()
    local info = { current = 0, headroom = 0, vilCount = 0 }
    pcall(function()
        info.current = GetFact(Fact.POPULATION)
        info.headroom = GetFact(Fact.POPULATION_HEADROOM)
        info.vilCount = GetFact(Fact.VILLAGER_COUNT)
    end)
    return info
end

local function canAfford(wood, food, gold, stone)
    local r = getResources()
    return (r.food or 0) >= (food or 0) and (r.wood or 0) >= (wood or 0)
        and (r.gold or 0) >= (gold or 0) and (r.stone or 0) >= (stone or 0)
end

-- ── Footprint check ──

local function isFootprintClear(cx, cy, size)
    local half = math.floor(size / 2)
    for dx = -half, half - 1 do
        for dy = -half, half - 1 do
            local tile = GetMapTile(math.floor(cx) + dx, math.floor(cy) + dy)
            if not tile then return false end
            local buildable, walkable = false, false
            pcall(function() buildable = tile:IsBuildable() end)
            pcall(function() walkable = tile:IsWalkable() end)
            if not buildable or not walkable then return false end
            local cnt = 0
            pcall(function() cnt = tile:GetObjectCount() end)
            if cnt > 0 then
                local blocked = false
                pcall(function()
                    for _, obj in ipairs(tile:GetObjects()) do
                        local clsOk, cls = pcall(function() return obj:GetClass() end)
                        if clsOk and cls ~= 904 and cls ~= 961 and cls ~= 958 then
                            blocked = true
                        end
                    end
                end)
                if blocked then return false end
            end
        end
    end
    return true
end

local function findClearSpot(cx, cy, size)
    local offsets = {
        {0,0},{2,0},{-2,0},{0,2},{0,-2},
        {2,2},{-2,2},{2,-2},{-2,-2},
        {4,0},{-4,0},{0,4},{0,-4},
        {4,2},{-4,2},{4,-2},{-4,-2},
        {6,0},{-6,0},{0,6},{0,-6},
    }
    for _, off in ipairs(offsets) do
        if isFootprintClear(cx + off[1], cy + off[2], size) then
            return Vector3(cx + off[1], cy + off[2], 0)
        end
    end
    return nil
end

-- ── Resource finding ──

local function findNearest(objects, near)
    if not objects or #objects == 0 then return nil end
    local best, bestDist = nil, 999999
    for _, obj in ipairs(objects) do
        local pos = obj:GetPosition()
        local d = dist(pos, near)
        if d < bestDist then best = obj; bestDist = d end
    end
    return best, bestDist
end

local function findFood(tcPos)
    if not tcPos then return nil end
    -- Sheep/livestock near TC first
    if strategy.resourceTracker then
        local ok, livestock = pcall(function()
            return strategy.resourceTracker:GetConvertibleLivestock(tcPos, 15)
        end)
        if ok and livestock and #livestock > 0 then
            return findNearest(livestock, tcPos)
        end
        -- Owned livestock
        local ok2, owned = pcall(function()
            return strategy.resourceTracker:GetOwnedLivestock()
        end)
        if ok2 and owned then
            local near = {}
            for _, o in ipairs(owned) do
                if dist(o:GetPosition(), tcPos) < 15 then table.insert(near, o) end
            end
            if #near > 0 then return findNearest(near, tcPos) end
        end
        -- Forage
        local ok3, forage = pcall(function() return strategy.resourceTracker:GetForage() end)
        if ok3 and forage then
            local best, d = findNearest(forage, tcPos)
            if best and d < 15 then return best, d end
        end
    end
    return nil
end

local function findTrees(tcPos)
    if not strategy.resourceTracker or not tcPos then return nil end
    local ok, trees = pcall(function() return strategy.resourceTracker:GetTrees() end)
    if not ok or not trees then return nil end
    local near = {}
    for _, t in ipairs(trees) do
        if dist(t:GetPosition(), tcPos) < 20 then table.insert(near, t) end
    end
    if #near == 0 then return nil end
    -- Prefer safe side
    local mapW, mapH = GetMapWidth(), GetMapHeight()
    local center = Vector3(mapW/2, mapH/2, 0)
    local safeX = tcPos.x - center.x
    local safeY = tcPos.y - center.y
    table.sort(near, function(a, b)
        local pa, pb = a:GetPosition(), b:GetPosition()
        local sa = (pa.x - tcPos.x) * safeX + (pa.y - tcPos.y) * safeY
        local sb = (pb.x - tcPos.x) * safeX + (pb.y - tcPos.y) * safeY
        return sa > sb
    end)
    return near[1]
end

local function findGold(tcPos)
    if not strategy.resourceTracker or not tcPos then return nil end
    local ok, gold = pcall(function() return strategy.resourceTracker:GetGold() end)
    if not ok or not gold then return nil end
    return findNearest(gold, tcPos)
end

-- ── Scout ──

local function doScout()
    if state.scoutDone then return end

    if not state.scoutId then
        pcall(function()
            local p = getPlayer()
            for _, u in ipairs(p:GetUnits()) do
                if u:IsAlive() and u:GetClass() == 961 then
                    state.scoutId = u
                    break
                end
            end
        end)
        if not state.scoutId then return end
    end

    if state.scoutWaypoint < 8 then
        if state.tick % 4 ~= 1 then return end
        local base = getVilCenter() or getTcPos()
        if not base then return end
        local mapW, mapH = GetMapWidth(), GetMapHeight()
        local center = Vector3(mapW/2, mapH/2, 0)
        local safeX, safeY = base.x - center.x, base.y - center.y
        local startAngle = math.atan2(safeY, safeX)
        local angle = startAngle + (state.scoutWaypoint / 8) * 2 * math.pi
        local tx = base.x + 15 * math.cos(angle)
        local ty = base.y + 15 * math.sin(angle)
        UnitsMove({state.scoutId}, Vector3(tx, ty, 0))
        state.scoutWaypoint = state.scoutWaypoint + 1
    else
        pcall(function() SetUnitStanceAutoScout({state.scoutId}) end)
        state.scoutDone = true
    end
end

-- ── TC ──

local function hasTc()
    return #getTcs() > 0
end

local function buildTc()
    if state.tcBuilt then return end
    if not canAfford(275, 0, 0, 100) then
        Log("[Strategy] Can't afford TC")
        return
    end
    local base = getVilCenter()
    if not base then
        Log("[Strategy] No vil center")
        return
    end
    local spot = findClearSpot(base.x, base.y, 4)
    if not spot then
        Log("[Strategy] No clear 4x4 spot near " .. math.floor(base.x) .. "," .. math.floor(base.y))
        return
    end
    local vils = getVils()
    if #vils == 0 then
        Log("[Strategy] No vils")
        return
    end
    local typeId = UnitObjectType["TOWN_CENTER_FOUNDATION"]
    if not typeId then
        Log("[Strategy] TC_FOUNDATION type not found, trying TOWN_CENTER")
        typeId = UnitObjectType["TOWN_CENTER"]
    end
    if not typeId then
        Log("[Strategy] No TC type found at all!")
        return
    end
    Log("[Strategy] Building TC type=" .. typeId .. " at " .. math.floor(spot.x) .. "," .. math.floor(spot.y) .. " with " .. #vils .. " vils")
    local ok = UnitsBuildStructure(vils, typeId, spot)
    Log("[Strategy] UnitsBuildStructure result: " .. tostring(ok))
    if ok then
        state.tcBuilt = true
    end
end

local function moveLivestockToBase()
    local base = getVilCenter()
    if not base or not strategy.resourceTracker then return end
    pcall(function()
        local owned = strategy.resourceTracker:GetOwnedLivestock()
        if owned and #owned > 0 then
            UnitsMove(owned, base)
        end
    end)
end

-- ── Train ──

local function trainVil()
    local tcs = getTcs()
    if #tcs == 0 then return end
    local pop = getPopInfo()
    if pop.vilCount >= 40 or pop.headroom <= 0 then return end
    if not canAfford(0, 50, 0, 0) then return end
    pcall(function() TrainUnit(tcs, UnitObjectType.VILLAGER_MALE, 1) end)
end

-- ── Houses ──

local function buildHouses()
    if state.houseCd > 0 then return end
    local pop = getPopInfo()
    if pop.headroom > 4 then return end
    if not canAfford(125, 0, 0, 0) then return end
    local tc = getTcPos()
    if not tc then return end
    local spot = findClearSpot(tc.x - 4, tc.y + 4, 2)
    if not spot then return end
    local vils = getIdleVils()
    if #vils == 0 then vils = getVils() end
    if #vils == 0 then return end
    -- Use just 1 vil
    if UnitsBuildStructure({vils[1]}, UnitObjectType.HOUSE_DARK_AGE or UnitObjectType.HOUSE, spot) then
        state.houseCd = 8
    end
end

-- ── Force all vils to food on TC complete ──

local function forceAllVilsToFood()
    local tc = getTcPos()
    if not tc then return end
    local food = findFood(tc)
    if not food then return end
    local vils = getVils()
    if #vils == 0 then return end
    UnitsTargetObject(vils, food)
    state.tcFoodForced = true
    Log("[Strategy] Forced " .. #vils .. " vils to food")
end

-- ── Build order assignment ──

local function assignByBuildOrder()
    local idle = getIdleVils()
    if #idle == 0 then return end

    local tc = getTcPos()
    if not tc then return end
    local pop = getPopInfo()
    local n = pop.vilCount

    -- Lock wood target once
    if not state.woodTarget then
        local tree = findTrees(tc)
        if tree then
            state.woodTarget = tree
            Log("[Strategy] LOCKED wood: " .. math.floor(tree:GetPosition().x) .. "," .. math.floor(tree:GetPosition().y))
        end
    end

    local food = findFood(tc)

    for _, vil in ipairs(idle) do
        if n <= 6 then
            if food then UnitsTargetObject({vil}, food) end
        elseif n <= 10 then
            if state.woodTarget then UnitsTargetObject({vil}, state.woodTarget) end
        elseif n <= 18 then
            if food then UnitsTargetObject({vil}, food) end
        elseif n <= 23 then
            if state.woodTarget then UnitsTargetObject({vil}, state.woodTarget) end
        elseif n <= 26 then
            local gold = findGold(tc)
            if gold then UnitsTargetObject({gold}, gold) end
        else
            local r = getResources()
            if (r.food or 0) < (r.wood or 0) and food then
                UnitsTargetObject({vil}, food)
            elseif state.woodTarget then
                UnitsTargetObject({vil}, state.woodTarget)
            end
        end
        n = n - 1
    end
end

-- ── Eco buildings ──

local function buildEcoBuildings()
    local tc = getTcPos()
    if not tc then return end
    local pop = getPopInfo()

    -- Lumber camp at vil 8
    if not state.built.lc and state.woodTarget and canAfford(100, 0, 0, 0) and pop.vilCount >= 8 then
        local wpos = state.woodTarget:GetPosition()
        local dx, dy = tc.x - wpos.x, tc.y - wpos.y
        local d = math.max(math.sqrt(dx*dx + dy*dy), 0.1)
        local lx, ly = wpos.x + dx/d * 4, wpos.y + dy/d * 4
        local spot = findClearSpot(lx, ly, 2)
        if spot then
            -- Find nearest wood vil to build it
            local vils = getVils()
            local builder = nil
            local bestDist = 999
            for _, v in ipairs(vils) do
                local vd = dist(v:GetPosition(), wpos)
                if vd < bestDist then builder = v; bestDist = vd end
            end
            if builder then
                local typeId = UnitObjectType.LUMBER_CAMP_DARK_AGE or UnitObjectType.LUMBER_CAMP
                if typeId and UnitsBuildStructure({builder}, typeId, spot) then
                    state.built.lc = true
                    Log("[Strategy] LC at " .. math.floor(spot.x) .. "," .. math.floor(spot.y))
                end
            end
        end
    end

    -- Mill at vil 12
    if not state.built.mill and state.built.lc and canAfford(100, 0, 0, 0) and pop.vilCount >= 12 then
        local forage = nil
        pcall(function()
            local f = strategy.resourceTracker:GetForage()
            if f and #f > 0 then
                local best, d = findNearest(f, tc)
                if best and d < 12 then forage = best end
            end
        end)
        local mx, my
        if forage then
            local fp = forage:GetPosition()
            local dx, dy = tc.x - fp.x, tc.y - fp.y
            local d = math.max(math.sqrt(dx*dx + dy*dy), 0.1)
            mx, my = fp.x + dx/d * 2, fp.y + dy/d * 2
        else
            mx, my = tc.x + 5, tc.y
        end
        local spot = findClearSpot(mx, my, 2)
        if spot then
            local vils = getIdleVils()
            if #vils == 0 then vils = getVils() end
            if #vils > 0 then
                local typeId = UnitObjectType.MILL_DARK_AGE or UnitObjectType.MILL
                if typeId and UnitsBuildStructure({vils[1]}, typeId, spot) then
                    state.built.mill = true
                    Log("[Strategy] Mill at " .. math.floor(spot.x) .. "," .. math.floor(spot.y))
                end
            end
        end
    end

    -- Mining camp at vil 24
    if not state.built.mc and canAfford(100, 0, 0, 0) and pop.vilCount >= 24 then
        local gold = findGold(tc)
        if gold then
            local gp = gold:GetPosition()
            local dx, dy = tc.x - gp.x, tc.y - gp.y
            local d = math.max(math.sqrt(dx*dx + dy*dy), 0.1)
            local spot = findClearSpot(gp.x + dx/d * 3, gp.y + dy/d * 3, 2)
            if spot then
                local vils = getIdleVils()
                if #vils == 0 then vils = getVils() end
                if #vils > 0 then
                    local typeId = UnitObjectType.MINING_CAMP_DARK_AGE or UnitObjectType.MINING_CAMP
                    if typeId and UnitsBuildStructure({vils[1]}, typeId, spot) then
                        state.built.mc = true
                        Log("[Strategy] MC built")
                    end
                end
            end
        end
    end
end

-- ── Livestock ──

local function herdNewLivestock()
    local tc = getTcPos()
    if not tc or not strategy.resourceTracker then return end
    pcall(function()
        local owned = strategy.resourceTracker:GetOwnedLivestock()
        if not owned then return end
        local far = {}
        for _, o in ipairs(owned) do
            if dist(o:GetPosition(), tc) > 8 then table.insert(far, o) end
        end
        if #far > 0 then UnitsMove(far, tc) end
    end)
end

-- ── Farms ──

local function buildFarms()
    if state.farmCd > 0 then return end
    if not state.built.mill then return end
    local r = getResources()
    if (r.food or 0) > 200 then return end
    if not canAfford(60, 0, 0, 0) then return end
    local tc = getTcPos()
    if not tc then return end
    local spot = findClearSpot(tc.x + 3, tc.y, 2)
    if not spot then return end
    local vils = getIdleVils()
    if #vils == 0 then vils = getVils() end
    if #vils > 0 then
        if UnitsBuildStructure({vils[1]}, UnitObjectType.FARM, spot) then
            state.farmCd = 15
        end
    end
end

-- ── Age goals ──

local function darkAgeGoals()
    local pop = getPopInfo()
    -- Loom at 24 vils
    if pop.vilCount >= 24 and canAfford(0, 50, 0, 0) then
        pcall(function()
            if not IsTechnologyResearched(22) then ResearchTechnology(22) end
        end)
    end
    -- Feudal: 2 dark buildings + 500 food
    if not state.feudalClicked and canAfford(0, 500, 0, 0) then
        local darkCount = 0
        pcall(function()
            local p = getPlayer()
            local objs = p:GetPlayerObjects()
            local seen = {}
            for _, o in ipairs(objs) do
                if o:IsAlive() then
                    local name = o:GetName() or ""
                    name = string.upper(name)
                    if string.find(name, "MILL") and not seen.mill then darkCount = darkCount + 1; seen.mill = true end
                    if string.find(name, "LUMBER") and not seen.lc then darkCount = darkCount + 1; seen.lc = true end
                    if string.find(name, "MINING") and not seen.mc then darkCount = darkCount + 1; seen.mc = true end
                    if string.find(name, "BARRACKS") and not seen.rax then darkCount = darkCount + 1; seen.rax = true end
                end
            end
        end)
        if darkCount >= 2 then
            pcall(function()
                if CanResearch(101) then
                    ResearchTechnology(101)
                    state.feudalClicked = true
                    Log("[Strategy] Feudal clicked")
                end
            end)
        end
    end
end

local function feudalGoals()
    local tc = getTcPos()
    if not tc then return end
    -- Blacksmith
    if canAfford(150, 0, 0, 0) then
        local spot = findClearSpot(tc.x + 8, tc.y + 4, 2)
        if spot then
            local vils = getIdleVils()
            if #vils > 0 then
                local typeId = UnitObjectType.BLACKSMITH or UnitObjectType.BLACKSMITH_FEUDAL_AGE
                if typeId then pcall(function() UnitsBuildStructure({vils[1]}, typeId, spot) end) end
            end
        end
    end
    -- Market
    if canAfford(175, 0, 0, 0) then
        local spot = findClearSpot(tc.x - 8, tc.y + 4, 2)
        if spot then
            local vils = getIdleVils()
            if #vils > 0 then
                local typeId = UnitObjectType.MARKET or UnitObjectType.MARKET_FEUDAL_AGE
                if typeId then pcall(function() UnitsBuildStructure({vils[1]}, typeId, spot) end) end
            end
        end
    end
    -- Double bit axe + horse collar
    pcall(function()
        if not IsTechnologyResearched(202) and CanResearch(202) then ResearchTechnology(202) end
        if not IsTechnologyResearched(14) and CanResearch(14) then ResearchTechnology(14) end
    end)
    -- Castle advance
    if not state.castleClicked and canAfford(0, 800, 200, 0) then
        pcall(function()
            if CanResearch(102) then
                ResearchTechnology(102)
                state.castleClicked = true
                Log("[Strategy] Castle clicked")
            end
        end)
    end
    buildFarms()
end

local function castleGoals()
    local tc = getTcPos()
    if not tc then return end
    -- 2nd TC
    if #getTcs() < 2 and canAfford(275, 0, 0, 100) then
        local spot = findClearSpot(tc.x + 10, tc.y, 4)
        if spot then
            local vils = getVils()
            if #vils > 0 then
                pcall(function()
                    UnitsBuildStructure({vils[1]}, UnitObjectType.TOWN_CENTER_FOUNDATION or UnitObjectType.TOWN_CENTER, spot)
                end)
            end
        end
    end
    -- Wheelbarrow
    pcall(function()
        if not IsTechnologyResearched(213) and CanResearch(213) then ResearchTechnology(213) end
    end)
    buildFarms()
end

-- ── Main update ──

function strategy.update(rt)
    strategy.resourceTracker = rt
    state.tick = state.tick + 1
    if state.houseCd > 0 then state.houseCd = state.houseCd - 1 end
    if state.farmCd > 0 then state.farmCd = state.farmCd - 1 end

    if state.tick == 1 then
        local r = getResources()
        Log("[Strategy] First tick - F:" .. r.food .. " W:" .. r.wood .. " G:" .. r.gold .. " S:" .. r.stone)
    end

    doScout()

    if not hasTc() then
        if state.tick % 10 == 1 then
            Log("[Strategy] No TC - building...")
        end
        buildTc()
        moveLivestockToBase()
        return
    end

    if not state.tcFoodForced then
        forceAllVilsToFood()
    end

    trainVil()
    buildHouses()
    assignByBuildOrder()
    buildEcoBuildings()
    herdNewLivestock()

    local age = getAge()
    if age == 0 then
        darkAgeGoals()
    elseif age == 1 then
        feudalGoals()
    elseif age >= 2 then
        castleGoals()
    end

    if state.built.mill then
        buildFarms()
    end
end

return strategy
