-- Fast Castle 27+2 Build Order
-- Runs autonomously from Update() — no Python bridge needed.

local strategy = {}

local state = {
    tick = 0,
    scoutId = nil,
    scoutWaypoint = 0,
    scoutDone = false,
    tcBuilt = false,
    tcFoodForced = false,
    livestockMoved = false,
    woodTarget = nil,
    built = {},
    houseCd = 0,
    farmCd = 0,
    feudalClicked = false,
    castleClicked = false,
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
        pcall(function() if v:IsIdle() then table.insert(idle, v) end end)
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
        local ok, pos = pcall(function() return obj:GetPosition() end)
        if ok and pos then
            local d = dist(pos, near)
            if d < bestDist then best = obj; bestDist = d end
        end
    end
    return best, bestDist
end

local function findFood(tcPos)
    if not tcPos or not strategy.resourceTracker then return nil end
    local ok, owned = pcall(function() return strategy.resourceTracker:GetOwnedLivestock() end)
    if ok and owned then
        local near = {}
        for _, o in ipairs(owned) do
            pcall(function()
                if dist(o:GetPosition(), tcPos) < 15 then table.insert(near, o) end
            end)
        end
        if #near > 0 then return findNearest(near, tcPos) end
    end
    local ok2, forage = pcall(function() return strategy.resourceTracker:GetForage() end)
    if ok2 and forage then
        local best, d = findNearest(forage, tcPos)
        if best and d < 15 then return best end
    end
    return nil
end

local function findTrees(tcPos)
    if not strategy.resourceTracker or not tcPos then return nil end
    local ok, trees = pcall(function() return strategy.resourceTracker:GetTrees() end)
    if not ok or not trees then return nil end
    local near = {}
    for _, t in ipairs(trees) do
        pcall(function()
            if dist(t:GetPosition(), tcPos) < 20 then table.insert(near, t) end
        end)
    end
    if #near == 0 then return nil end
    local mapW, mapH = GetMapWidth(), GetMapHeight()
    local center = Vector3(mapW/2, mapH/2, 0)
    local safeX = tcPos.x - center.x
    local safeY = tcPos.y - center.y
    table.sort(near, function(a, b)
        local pOk1, pa = pcall(function() return a:GetPosition() end)
        local pOk2, pb = pcall(function() return b:GetPosition() end)
        if not pOk1 or not pOk2 then return false end
        return (pa.x - tcPos.x) * safeX + (pa.y - tcPos.y) * safeY >
               (pb.x - tcPos.x) * safeX + (pb.y - tcPos.y) * safeY
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
            for _, u in ipairs(p:GetObjectsByClass(961)) do
                if u:IsAlive() then state.scoutId = u; break end
            end
        end)
        if not state.scoutId then return end
    end
    if state.scoutWaypoint < 8 then
        if state.tick % 4 ~= 1 then return end
        local base = getVilCenter() or getTcPos()
        if not base then return end
        local mapW, mapH = GetMapWidth(), GetMapHeight()
        local safeX, safeY = base.x - mapW/2, base.y - mapH/2
        local startAngle = math.atan2(safeY, safeX)
        local angle = startAngle + (state.scoutWaypoint / 8) * 2 * math.pi
        pcall(function()
            UnitsMove({state.scoutId}, Vector3(base.x + 15 * math.cos(angle), base.y + 15 * math.sin(angle), 0))
        end)
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
    if not canAfford(275, 0, 0, 100) then return end
    local base = getVilCenter()
    if not base then return end
    local spot = findClearSpot(base.x, base.y, 4)
    if not spot then
        Log("[Strategy] No clear spot for TC")
        return
    end
    local vils = getVils()
    if #vils == 0 then return end
    local typeId = UnitObjectType["TOWN_CENTER_FOUNDATION"]
    if not typeId then typeId = UnitObjectType["TOWN_CENTER_DARK_AGE"] end
    if not typeId then return end
    Log("[Strategy] Building TC at " .. math.floor(spot.x) .. "," .. math.floor(spot.y))
    if UnitsBuildStructure(vils, typeId, spot) then
        state.tcBuilt = true
    end
end

local function moveLivestockToBase()
    if state.livestockMoved then return end
    local base = getVilCenter()
    if not base or not strategy.resourceTracker then return end
    pcall(function()
        local owned = strategy.resourceTracker:GetOwnedLivestock()
        if owned and #owned > 0 then
            UnitsMove(owned, base)
            state.livestockMoved = true
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
    pcall(function() TrainUnit(tcs, UnitObjectType["VILLAGER_MALE"], 1) end)
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
    local typeId = UnitObjectType["HOUSE_DARK_AGE"] or UnitObjectType["HOUSE"]
    if typeId and UnitsBuildStructure({vils[1]}, typeId, spot) then
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
    pcall(function() UnitsTargetObject(vils, food) end)
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

    if not state.woodTarget then
        local tree = findTrees(tc)
        if tree then
            state.woodTarget = tree
            pcall(function()
                Log("[Strategy] LOCKED wood: " .. math.floor(tree:GetPosition().x) .. "," .. math.floor(tree:GetPosition().y))
            end)
        end
    end

    -- Refresh wood target if it died
    if state.woodTarget then
        local ok, alive = pcall(function() return state.woodTarget:IsAlive() end)
        if not ok or not alive then
            state.woodTarget = nil
            local tree = findTrees(tc)
            if tree then state.woodTarget = tree end
        end
    end

    local food = findFood(tc)

    -- All idle vils get same assignment based on current vil count
    for _, vil in ipairs(idle) do
        pcall(function()
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
                if gold then UnitsTargetObject({vil}, gold) end
            else
                local r = getResources()
                if r.food < r.wood and food then
                    UnitsTargetObject({vil}, food)
                elseif state.woodTarget then
                    UnitsTargetObject({vil}, state.woodTarget)
                end
            end
        end)
    end
end

-- ── Eco buildings ──

local function buildEcoBuildings()
    local tc = getTcPos()
    if not tc then return end
    local pop = getPopInfo()

    -- Lumber camp at vil 8
    if not state.built.lc and state.woodTarget and canAfford(100, 0, 0, 0) and pop.vilCount >= 8 then
        local ok, wpos = pcall(function() return state.woodTarget:GetPosition() end)
        if ok and wpos then
            local dx, dy = tc.x - wpos.x, tc.y - wpos.y
            local d = math.max(math.sqrt(dx*dx + dy*dy), 0.1)
            local spot = findClearSpot(wpos.x + dx/d * 4, wpos.y + dy/d * 4, 2)
            if spot then
                local vils = getVils()
                local builder = nil; local bestDist = 999
                for _, v in ipairs(vils) do
                    pcall(function()
                        local vd = dist(v:GetPosition(), wpos)
                        if vd < bestDist then builder = v; bestDist = vd end
                    end)
                end
                if builder then
                    local typeId = UnitObjectType["LUMBER_CAMP_DARK_AGE"]
                    if typeId and UnitsBuildStructure({builder}, typeId, spot) then
                        state.built.lc = true
                        Log("[Strategy] LC at " .. math.floor(spot.x) .. "," .. math.floor(spot.y))
                    end
                end
            end
        end
    end

    -- Mill at vil 12
    if not state.built.mill and state.built.lc and canAfford(100, 0, 0, 0) and pop.vilCount >= 12 then
        local mx, my = tc.x + 5, tc.y
        pcall(function()
            local f = strategy.resourceTracker:GetForage()
            if f and #f > 0 then
                local best, d = findNearest(f, tc)
                if best and d < 12 then
                    local fp = best:GetPosition()
                    local dx, dy = tc.x - fp.x, tc.y - fp.y
                    local dd = math.max(math.sqrt(dx*dx + dy*dy), 0.1)
                    mx, my = fp.x + dx/dd * 2, fp.y + dy/dd * 2
                end
            end
        end)
        local spot = findClearSpot(mx, my, 2)
        if spot then
            local vils = getIdleVils()
            if #vils == 0 then vils = getVils() end
            if #vils > 0 then
                local typeId = UnitObjectType["MILL_DARK_AGE"] or UnitObjectType["MILL"]
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
            local ok, gp = pcall(function() return gold:GetPosition() end)
            if ok and gp then
                local dx, dy = tc.x - gp.x, tc.y - gp.y
                local d = math.max(math.sqrt(dx*dx + dy*dy), 0.1)
                local spot = findClearSpot(gp.x + dx/d * 3, gp.y + dy/d * 3, 2)
                if spot then
                    local vils = getIdleVils()
                    if #vils == 0 then vils = getVils() end
                    if #vils > 0 then
                        local typeId = UnitObjectType["MINING_CAMP_DARK_AGE"]
                        if typeId and UnitsBuildStructure({vils[1]}, typeId, spot) then
                            state.built.mc = true
                            Log("[Strategy] MC built")
                        end
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
    local pop = getPopInfo()
    if pop.vilCount < 8 then return end
    pcall(function()
        local owned = strategy.resourceTracker:GetOwnedLivestock()
        if not owned then return end
        local far = {}
        for _, o in ipairs(owned) do
            pcall(function()
                if dist(o:GetPosition(), tc) > 8 then table.insert(far, o) end
            end)
        end
        if #far > 0 then UnitsMove(far, tc) end
    end)
end

-- ── Farms ──

local function buildFarms()
    if state.farmCd > 0 then return end
    if not state.built.mill then return end
    local r = getResources()
    if r.food > 200 then return end
    if not canAfford(60, 0, 0, 0) then return end
    local tc = getTcPos()
    if not tc then return end
    local spot = findClearSpot(tc.x + 3, tc.y, 2)
    if not spot then return end
    local vils = getIdleVils()
    if #vils == 0 then vils = getVils() end
    if #vils > 0 then
        if UnitsBuildStructure({vils[1]}, UnitObjectType["FARM"], spot) then
            state.farmCd = 15
        end
    end
end

-- ── Age goals ──

local function darkAgeGoals()
    local pop = getPopInfo()
    -- Loom at 24 vils (costs 50 gold)
    if pop.vilCount >= 24 and canAfford(0, 0, 50, 0) then
        pcall(function()
            if not IsTechnologyResearched(22) then ResearchTechnology(22) end
        end)
    end
    -- Feudal: 2 dark buildings + 500 food
    if not state.feudalClicked and canAfford(0, 500, 0, 0) then
        local darkCount = 0
        pcall(function()
            local p = getPlayer()
            for _, o in ipairs(p:GetPlayerObjects()) do
                local nameOk, name = pcall(function() return string.upper(o:GetName() or "") end)
                local aliveOk, alive = pcall(function() return o:IsAlive() end)
                if nameOk and aliveOk and alive then
                    if string.find(name, "MILL") and not state.built._millCounted then darkCount = darkCount + 1; state.built._millCounted = true end
                    if string.find(name, "LUMBER") and not state.built._lcCounted then darkCount = darkCount + 1; state.built._lcCounted = true end
                    if string.find(name, "MINING") and not state.built._mcCounted then darkCount = darkCount + 1; state.built._mcCounted = true end
                    if string.find(name, "BARRACKS") and not state.built._raxCounted then darkCount = darkCount + 1; state.built._raxCounted = true end
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
        -- Reset counted flags for next tick
        state.built._millCounted = nil; state.built._lcCounted = nil
        state.built._mcCounted = nil; state.built._raxCounted = nil
    end
end

local function feudalGoals()
    local tc = getTcPos()
    if not tc then return end
    if not state.built.blacksmith and canAfford(150, 0, 0, 0) then
        local spot = findClearSpot(tc.x + 8, tc.y + 4, 2)
        if spot then
            local vils = getIdleVils()
            if #vils > 0 then
                local typeId = UnitObjectType["BLACKSMITH_FEUDAL_AGE"] or UnitObjectType["BLACKSMITH"]
                if typeId then
                    pcall(function()
                        if UnitsBuildStructure({vils[1]}, typeId, spot) then
                            state.built.blacksmith = true
                            Log("[Strategy] Blacksmith built")
                        end
                    end)
                end
            end
        end
    end
    if not state.built.market and canAfford(175, 0, 0, 0) then
        local spot = findClearSpot(tc.x - 8, tc.y + 4, 2)
        if spot then
            local vils = getIdleVils()
            if #vils > 0 then
                local typeId = UnitObjectType["MARKET_FEUDAL_AGE"] or UnitObjectType["MARKET"]
                if typeId then
                    pcall(function()
                        if UnitsBuildStructure({vils[1]}, typeId, spot) then
                            state.built.market = true
                            Log("[Strategy] Market built")
                        end
                    end)
                end
            end
        end
    end
    pcall(function()
        if not IsTechnologyResearched(202) and CanResearch(202) then ResearchTechnology(202) end
        if not IsTechnologyResearched(14) and CanResearch(14) then ResearchTechnology(14) end
    end)
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
    if #getTcs() < 2 and canAfford(275, 0, 0, 100) then
        local spot = findClearSpot(tc.x + 10, tc.y, 4)
        if spot then
            local vils = getVils()
            if #vils > 0 then
                local age = getAge()
                local typeId
                if age >= 2 then typeId = UnitObjectType["TOWN_CENTER_CASTLE_AGE"]
                elseif age >= 1 then typeId = UnitObjectType["TOWN_CENTER_FEUDAL_AGE"]
                else typeId = UnitObjectType["TOWN_CENTER_DARK_AGE"] end
                if typeId then
                    pcall(function() UnitsBuildStructure({vils[1]}, typeId, spot) end)
                end
            end
        end
    end
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
        Log("[Strategy] Start F:" .. r.food .. " W:" .. r.wood .. " G:" .. r.gold .. " S:" .. r.stone)
    end

    doScout()

    if not hasTc() then
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
        buildFarms()
    elseif age == 1 then
        feudalGoals()
    elseif age >= 2 then
        castleGoals()
    end
end

return strategy
