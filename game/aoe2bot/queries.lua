-- AoE2Bot query handlers
-- All read-only game state queries. No side effects on the game world.

local queries = {}

-- Module-level references set by main.lua after require
queries.helpersReady = false
queries.resourceTracker = nil
queries.vilOccupation = nil
queries.construction = nil
queries.util = nil  -- set by main.lua

function queries.getState()
    local safeGetFact = queries.util.safeGetFact

    local p = GetAssignedPlayer()
    if not p then
        return { action = "state", error = "no assigned player" }
    end

    local state = {
        action = "state",
        playerId = GetAssignedPlayerId(),
        time = GetGameTime(),
        paused = IsGamePaused(),
        helpersReady = queries.helpersReady,
    }

    pcall(function() state.playerName = p:GetPlayerName() end)
    pcall(function() state.civilization = p:GetCivilizationName() end)
    pcall(function() state.civId = p:GetCivilizationId() end)

    state.resources = {
        food = safeGetFact(Fact.FOOD_AMOUNT),
        wood = safeGetFact(Fact.WOOD_AMOUNT),
        gold = safeGetFact(Fact.GOLD_AMOUNT),
        stone = safeGetFact(Fact.STONE_AMOUNT),
    }

    state.population = {
        current = safeGetFact(Fact.POPULATION),
        headroom = safeGetFact(Fact.POPULATION_HEADROOM),
        housing_headroom = safeGetFact(Fact.HOUSING_HEADROOM),
    }

    state.age = safeGetFact(Fact.CURRENT_AGE)

    pcall(function()
        local vils = p:GetObjectsByClass(UnitClass.VILLAGER)
        local total, idle = 0, 0
        for _, v in ipairs(vils) do
            if v:IsAlive() and v:GetOwningPlayer():GetId() == p:GetId() then
                total = total + 1
                if v:IsIdle() then idle = idle + 1 end
            end
        end
        state.villagerCount = total
        state.idleVillagers = idle
    end)

    -- Villager occupation breakdown if helpers ready
    if queries.helpersReady and queries.vilOccupation then
        pcall(function()
            state.occupation = {
                total = queries.vilOccupation:GetVillagerCount(),
                idle = queries.vilOccupation:GetIdleVillagerCount(),
            }
        end)
    end

    return state
end

function queries.scanWorld(msg)
    local unitClass = msg.unit_class
    if not unitClass then return { action = "error", error = "missing unit_class" } end
    local limit = msg.limit or 20

    local results = {}
    pcall(function()
        local objects = GetObjectsByClass(unitClass)
        for i, obj in ipairs(objects) do
            if i > limit then break end
            local pos = obj:GetPosition()
            local entry = { id = obj:GetId(), x = pos.x, y = pos.y }
            pcall(function() entry.name = obj:GetName() end)
            pcall(function() entry.type = obj:GetUnitObjectType() end)
            pcall(function() entry.playerId = obj:GetOwningPlayer():GetId() end)
            table.insert(results, entry)
        end
    end)
    return { action = "world_scan", count = #results, objects = results }
end

function queries.scanResources()
    if not queries.helpersReady or not queries.resourceTracker then
        return { action = "error", error = "ResourceTracker not initialized" }
    end

    local result = { action = "resource_scan" }

    pcall(function()
        local trees = queries.resourceTracker:GetTrees()
        result.treeCount = #trees
        result.trees = {}
        for i, t in ipairs(trees) do
            if i > 10 then break end
            local pos = t:GetPosition()
            table.insert(result.trees, { id = t:GetId(), x = pos.x, y = pos.y })
        end
    end)

    pcall(function()
        local gold = queries.resourceTracker:GetGold()
        result.goldCount = #gold
        result.gold = {}
        for i, g in ipairs(gold) do
            if i > 10 then break end
            local pos = g:GetPosition()
            table.insert(result.gold, { id = g:GetId(), x = pos.x, y = pos.y })
        end
    end)

    pcall(function()
        local stone = queries.resourceTracker:GetStone()
        result.stoneCount = #stone
        result.stone = {}
        for i, s in ipairs(stone) do
            if i > 10 then break end
            local pos = s:GetPosition()
            table.insert(result.stone, { id = s:GetId(), x = pos.x, y = pos.y })
        end
    end)

    pcall(function()
        local forage = queries.resourceTracker:GetForage()
        result.forageCount = #forage
        result.forage = {}
        for i, f in ipairs(forage) do
            if i > 10 then break end
            local pos = f:GetPosition()
            table.insert(result.forage, { id = f:GetId(), x = pos.x, y = pos.y })
        end
    end)

    return result
end

function queries.scanLivestock()
    if not queries.helpersReady or not queries.resourceTracker then
        return { action = "error", error = "ResourceTracker not initialized" }
    end

    local result = { action = "livestock_scan", convertible = {}, owned = {} }

    pcall(function()
        local p = GetAssignedPlayer()
        if not p then return end
        local tcs = p:GetTownCenters()
        local tcPos = nil
        if #tcs > 0 then tcPos = tcs[1]:GetPosition() end

        local conv = queries.resourceTracker:GetConvertibleLivestock(tcPos or Vector3(100,100,0), 100)
        for i, obj in ipairs(conv) do
            if i > 20 then break end
            local pos = obj:GetPosition()
            table.insert(result.convertible, { id = obj:GetId(), x = pos.x, y = pos.y })
        end

        local owned = queries.resourceTracker:GetOwnedLivestock()
        for i, obj in ipairs(owned) do
            if i > 20 then break end
            local pos = obj:GetPosition()
            table.insert(result.owned, { id = obj:GetId(), x = pos.x, y = pos.y })
        end
    end)

    return result
end

function queries.getUnits(msg)
    local p = GetAssignedPlayer()
    if not p then
        return { action = "units", count = 0, units = {} }
    end

    local units = {}
    pcall(function()
        local objects
        if msg.unit_class then
            objects = p:GetObjectsByClass(msg.unit_class)
        else
            objects = p:GetPlayerObjects()
        end

        for _, obj in ipairs(objects) do
            if obj:IsAlive() and obj:GetOwningPlayer():GetId() == p:GetId() then
                local pos = obj:GetPosition()
                local entry = {
                    id = obj:GetId(),
                    name = "",
                    hp = 0, maxHp = 0,
                    x = pos.x, y = pos.y, z = pos.z,
                    idle = false, moving = false,
                }
                pcall(function() entry.name = obj:GetName() end)
                pcall(function() entry.type = obj:GetUnitObjectType() end)
                pcall(function() entry.hp = obj:GetHitpoints() end)
                pcall(function() entry.maxHp = obj:GetMaxHitpoints() end)
                pcall(function() entry.idle = obj:IsIdle() end)
                pcall(function() entry.moving = obj:IsMoving() end)
                pcall(function() entry.class = obj:GetClass() end)
                table.insert(units, entry)
            end
        end
    end)

    return {
        action = "units",
        playerId = GetAssignedPlayerId(),
        time = GetGameTime(),
        count = #units,
        units = units,
    }
end

function queries.getBuildings()
    local p = GetAssignedPlayer()
    if not p then
        return { action = "buildings", count = 0, buildings = {} }
    end

    local buildings = {}
    pcall(function()
        local objects = p:GetPlayerObjects()
        for _, obj in ipairs(objects) do
            if obj:IsAlive() and obj:GetOwningPlayer():GetId() == p:GetId() then
                local isBuilding = false
                pcall(function()
                    local cls = obj:GetClass()
                    if cls == UnitClass.BUILDING or cls == UnitClass.WALL or
                       cls == UnitClass.TOWER or cls == UnitClass.GATE or
                       cls == UnitClass.MONASTERY then
                        isBuilding = true
                    end
                end)

                if isBuilding then
                    local pos = obj:GetPosition()
                    local entry = { id = obj:GetId(), x = pos.x, y = pos.y, z = pos.z }
                    pcall(function() entry.name = obj:GetName() end)
                    pcall(function() entry.type = obj:GetUnitObjectType() end)
                    pcall(function() entry.hp = obj:GetHitpoints() end)
                    pcall(function() entry.maxHp = obj:GetMaxHitpoints() end)
                    table.insert(buildings, entry)
                end
            end
        end
    end)

    return {
        action = "buildings",
        playerId = GetAssignedPlayerId(),
        time = GetGameTime(),
        count = #buildings,
        buildings = buildings,
    }
end

function queries.getTownCenters()
    local tcs = {}
    pcall(function()
        local p = GetAssignedPlayer()
        local centers = p:GetTownCenters()
        for _, tc in ipairs(centers) do
            local pos = tc:GetPosition()
            local entry = { id = tc:GetId(), x = pos.x, y = pos.y }
            pcall(function() entry.hp = tc:GetHitpoints() end)
            pcall(function() entry.maxHp = tc:GetMaxHitpoints() end)
            pcall(function() entry.name = tc:GetName() end)
            table.insert(tcs, entry)
        end
    end)
    return { action = "town_centers", count = #tcs, tcs = tcs }
end

function queries.getMapTiles(msg)
    local x1 = msg.x1 or 0
    local y1 = msg.y1 or 0
    local x2 = msg.x2 or 20
    local y2 = msg.y2 or 20
    if (x2 - x1) > 30 then x2 = x1 + 30 end
    if (y2 - y1) > 30 then y2 = y1 + 30 end

    local tiles = {}
    pcall(function()
        for x = x1, x2 do
            for y = y1, y2 do
                local tile = GetMapTile(x, y)
                if tile then
                    table.insert(tiles, {
                        x = x, y = y,
                        terrain = tile:GetTerrain(),
                        elevation = tile:GetElevation(),
                        walkable = tile:IsWalkable(),
                        buildable = tile:IsBuildable(),
                    })
                end
            end
        end
    end)
    return { action = "map_tiles", count = #tiles, tiles = tiles }
end

function queries.getPlayers()
    local players = {}
    pcall(function()
        local count = GetPlayerCount()
        local me = GetAssignedPlayer()
        for i = 0, count - 1 do
            local p = GetPlayerById(i)
            if p then
                local entry = { id = p:GetId(), name = "", civilization = "", isEnemy = false }
                pcall(function() entry.name = p:GetPlayerName() end)
                pcall(function() entry.civilization = p:GetCivilizationName() end)
                pcall(function() entry.type = p:GetPlayerType() end)
                if i > 0 and me then
                    pcall(function() entry.isEnemy = IsEnemyPlayer(p) end)
                    pcall(function() entry.isAlly = me:IsAlliedWith(p) end)
                end
                table.insert(players, entry)
            end
        end
    end)
    return { action = "players", myPlayerId = GetAssignedPlayerId(), count = #players, players = players }
end

function queries.runDiagnostics()
    local diag = {
        action = "diagnostics",
        playerId = GetAssignedPlayerId(),
        time = GetGameTime(),
        helpersReady = queries.helpersReady,
        checks = {},
    }

    local enums = {
        "PlayerAttribute", "Fact", "UnitObjectType", "UnitClass",
        "Technology", "Age", "ResourceType", "UnitCombatStance",
        "TileVisibility", "VillagerProfession", "PlacementDirection",
    }
    for _, name in ipairs(enums) do
        local exists = _G[name] ~= nil
        diag.checks[name] = exists
        if exists and type(_G[name]) == "table" then
            local keys = {}
            local count = 0
            for k, _ in pairs(_G[name]) do
                if count < 5 then
                    table.insert(keys, k)
                    count = count + 1
                end
            end
            diag.checks[name .. "_sample"] = keys
        end
    end

    local factTests = {}
    local ok, val
    ok, val = pcall(GetFact, Fact.FOOD_AMOUNT); factTests["FOOD_AMOUNT"] = ok and val or "ERROR"
    ok, val = pcall(GetFact, Fact.WOOD_AMOUNT); factTests["WOOD_AMOUNT"] = ok and val or "ERROR"
    ok, val = pcall(GetFact, Fact.GOLD_AMOUNT); factTests["GOLD_AMOUNT"] = ok and val or "ERROR"
    ok, val = pcall(GetFact, Fact.STONE_AMOUNT); factTests["STONE_AMOUNT"] = ok and val or "ERROR"
    ok, val = pcall(GetFact, Fact.POPULATION); factTests["POPULATION"] = ok and val or "ERROR"
    ok, val = pcall(GetFact, Fact.CURRENT_AGE); factTests["CURRENT_AGE"] = ok and val or "ERROR"
    ok, val = pcall(GetFact, Fact.HOUSING_HEADROOM); factTests["HOUSING_HEADROOM"] = ok and val or "ERROR"
    ok, val = pcall(GetGameTime); factTests["GetGameTime"] = ok and val or "ERROR"
    diag.facts = factTests

    ok, val = pcall(function()
        local p = GetAssignedPlayer()
        return { id = p:GetId(), name = p:GetPlayerName(), civ = p:GetCivilizationName() }
    end)
    diag.player = ok and val or "ERROR"

    -- Helper status
    diag.helpers = {
        resourceTracker = queries.resourceTracker ~= nil,
        vilOccupation = queries.vilOccupation ~= nil,
        construction = queries.construction ~= nil,
    }
    if queries.helpersReady and queries.vilOccupation then
        pcall(function()
            diag.helpers.villagerCount = queries.vilOccupation:GetVillagerCount()
            diag.helpers.idleCount = queries.vilOccupation:GetIdleVillagerCount()
        end)
    end

    return diag
end

function queries.cmdGetTechState(msg)
    local results = {}
    for _, techId in ipairs(msg.technologies or {}) do
        local entry = { researched = false, available = false }
        pcall(function() entry.researched = IsTechnologyResearched(techId) end)
        pcall(function() entry.available = CanResearch(techId) end)
        results[tostring(techId)] = entry
    end
    return { action = "tech_state", technologies = results }
end

function queries.cmdGetBuildingCounts()
    local p = GetAssignedPlayer()
    if not p then return { action = "building_counts", counts = {}, buildings = {} } end

    local counts = {}
    local details = {}
    pcall(function()
        local objects = p:GetPlayerObjects()
        for _, obj in ipairs(objects) do
            if obj:IsAlive() and obj:GetOwningPlayer():GetId() == p:GetId() then
                local isBuilding = false
                pcall(function()
                    local cls = obj:GetClass()
                    if cls == UnitClass.BUILDING or cls == UnitClass.WALL or
                       cls == UnitClass.TOWER or cls == UnitClass.GATE or
                       cls == UnitClass.MONASTERY then
                        isBuilding = true
                    end
                end)
                if isBuilding then
                    local name = ""
                    pcall(function() name = obj:GetName() end)
                    if name ~= "" then
                        local base = name:match("^(.-)_[A-Z]+_AGE$") or name
                        local hp = obj:GetHitpoints()
                        local maxHp = obj:GetMaxHitpoints()
                        local complete = (maxHp > 0 and hp >= maxHp)
                        if complete then
                            counts[base] = (counts[base] or 0) + 1
                        end
                        local pos = obj:GetPosition()
                        table.insert(details, {
                            name = base, hp = hp, maxHp = maxHp,
                            complete = complete,
                            pct = maxHp > 0 and math.floor(hp / maxHp * 100) or 0,
                            x = pos.x, y = pos.y,
                        })
                    end
                end
            end
        end
    end)
    return { action = "building_counts", counts = counts, buildings = details }
end

function queries.cmdScanAvailable(msg)
    local results = { buildings = {}, units = {}, techs = {} }

    -- Check all UnitObjectType entries for availability
    for name, id in pairs(UnitObjectType) do
        if type(id) == "number" then
            local avail = IsObjectTypeAvailable(id)
            if avail then
                local afford = CanAfford(id, true)
                local costs = {}
                local ok, costData = pcall(GetObjectCost, id)
                if ok and costData then
                    for _, entry in ipairs(costData) do
                        costs[tostring(entry.resourceId)] = entry.amount
                    end
                end
                table.insert(results.buildings, {
                    name = name, id = id, available = true, canAfford = afford, costs = costs
                })
            end
        end
    end

    -- Check unit training availability (common units)
    local unitChecks = {
        { name = "VILLAGER_MALE", id = 83 },
        { name = "MILITIA", id = 74 },
        { name = "MAN_AT_ARMS", id = 75 },
        { name = "ARCHER", id = 4 },
        { name = "SKIRMISHER", id = 7 },
        { name = "SPEARMAN", id = 93 },
        { name = "SCOUT_CAVALRY", id = 448 },
        { name = "KNIGHT", id = 38 },
        { name = "CROSSBOW", id = 24 },
        { name = "MONK", id = 125 },
        { name = "BATTERING_RAM", id = 35 },
        { name = "TREBUCHET_PACKED", id = 331 },
    }
    for _, u in ipairs(unitChecks) do
        local avail = IsObjectTypeAvailable(u.id)
        local afford = CanAfford(u.id, false)
        results.units[u.name] = { id = u.id, available = avail, canAfford = afford }
    end

    -- Check tech availability
    local techChecks = {
        { name = "LOOM", id = 22 },
        { name = "FEUDAL_AGE", id = 101 },
        { name = "CASTLE_AGE", id = 102 },
        { name = "IMPERIAL_AGE", id = 103 },
        { name = "WHEELBARROW", id = 213 },
        { name = "HAND_CART", id = 249 },
        { name = "DOUBLE_BIT_AXE", id = 202 },
        { name = "BOW_SAW", id = 203 },
        { name = "HORSE_COLLAR", id = 14 },
        { name = "HEAVY_PLOW", id = 13 },
        { name = "GOLD_MINING", id = 55 },
        { name = "STONE_MINING", id = 278 },
        { name = "FLETCHING", id = 199 },
        { name = "FORGING", id = 67 },
    }
    for _, t in ipairs(techChecks) do
        local researched = IsTechnologyResearched(t.id)
        local canRes = CanResearch(t.id)
        results.techs[t.name] = { id = t.id, researched = researched, canResearch = canRes }
    end

    return { action = "scan_available", results = results }
end

return queries
