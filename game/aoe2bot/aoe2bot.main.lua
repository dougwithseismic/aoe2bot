-- AoE2Bot Bridge Module for AoE2Control
-- Exposes game state and command execution via named pipe IPC.
-- Uses ResourceTracker, VillagerOccupation, and ConstructionPlacement helpers.

local PIPE_NAME = "AoE2Bot_Pipe"
local pipe_connected = false

local resourceTracker = nil
local vilOccupation = nil
local construction = nil
local helpersReady = false

function Load(playerId)
    Log("[AoE2Bot] Loading for player " .. tostring(playerId))
end

function Init()
    pipe_connected = IPC.StartServer(PIPE_NAME)
    if pipe_connected then
        Log("[AoE2Bot] IPC server started on pipe: " .. PIPE_NAME)
    else
        Log("[AoE2Bot] ERROR: Failed to start IPC server")
    end

    local ok, err = pcall(function()
        resourceTracker = ResourceTracker:new()
        vilOccupation = VillagerOccupation:new(resourceTracker)
        construction = ConstructionPlacement:new(vilOccupation)
        helpersReady = true
    end)
    if ok then
        Log("[AoE2Bot] Helpers initialized (ResourceTracker, VillagerOccupation, ConstructionPlacement)")
    else
        Log("[AoE2Bot] WARNING: Helper init failed: " .. tostring(err))
        helpersReady = false
    end
end

function Update()
    if helpersReady then
        pcall(function() resourceTracker:Update() end)
        -- NOT calling construction:Update() or ProcessBuildingRequests()
        -- Python controls all building via place_building / smart_build commands
    end

    if not pipe_connected then return end
    if not IPC.HasMessages() then return end

    for _, raw in ipairs(IPC.GetMessages()) do
        local msg = ParseJSON(raw)
        if msg and msg.action then
            local ok, result = pcall(handleAction, msg)
            if ok and result then
                result.reqId = msg.reqId
                IPC.Send(result)
            elseif not ok then
                IPC.Send({
                    action = "error",
                    error = tostring(result),
                    request = msg.action,
                    reqId = msg.reqId
                })
            end
        end
    end
end

function End(hasWon)
    if pipe_connected then
        IPC.Send({ action = "game_ended", won = hasWon })
    end
end

function Unload()
    IPC.StopServer()
    pipe_connected = false
end

-- ─── Command Router ──────────────────────────────────────────────────────────

function handleAction(msg)
    local a = msg.action

    -- Connection
    if a == "ping" then
        return {
            action = "pong",
            playerId = GetAssignedPlayerId(),
            time = GetGameTime(),
            helpersReady = helpersReady,
        }

    elseif a == "init_helpers" then
        return initHelpers()

    -- State queries
    elseif a == "get_state" then return getState()
    elseif a == "get_units" then return getUnits(msg)
    elseif a == "get_buildings" then return getBuildings()
    elseif a == "get_town_centers" then return getTownCenters()
    elseif a == "get_map" then
        return { action = "map_info", width = GetMapWidth(), height = GetMapHeight(), time = GetGameTime() }
    elseif a == "get_map_tiles" then return getMapTiles(msg)
    elseif a == "get_players" then return getPlayers()
    elseif a == "scan_world" then return scanWorld(msg)
    elseif a == "scan_resources" then return scanResources()
    elseif a == "scan_livestock" then return scanLivestock()
    elseif a == "diag" then return runDiagnostics()
    elseif a == "enum_lookup" then return enumLookup(msg)
    elseif a == "get_tech_state" then return cmdGetTechState(msg)
    elseif a == "get_building_counts" then return cmdGetBuildingCounts()
    elseif a == "set_vil_priorities" then return cmdSetVilPriorities(msg)

    -- Training
    elseif a == "train" then return cmdTrain(msg)
    elseif a == "train_by_name" then return cmdTrainByName(msg)

    -- Building (raw)
    elseif a == "build" then return cmdBuild(msg)
    elseif a == "build_by_name" then return cmdBuildByName(msg)
    elseif a == "place_building" then return cmdPlaceBuilding(msg)

    -- Smart building (ConstructionPlacement)
    elseif a == "smart_build" then return cmdSmartBuild(msg)
    elseif a == "find_placement" then return cmdFindPlacement(msg)
    elseif a == "queue_build" then return cmdQueueBuild(msg)
    elseif a == "get_farm_placement" then return cmdGetFarmPlacement()

    -- Research
    elseif a == "research" then return cmdResearch(msg)
    elseif a == "research_by_name" then return cmdResearchByName(msg)

    -- Unit commands
    elseif a == "move" then return cmdMove(msg)
    elseif a == "attack" then return cmdAttack(msg)
    elseif a == "attack_move" then return cmdAttackMove(msg)
    elseif a == "patrol" then return cmdPatrol(msg)
    elseif a == "garrison" then return cmdGarrison(msg)
    elseif a == "scout" then return cmdAutoScout(msg)
    elseif a == "set_stance" then return cmdSetStance(msg)
    elseif a == "set_gather_point" then return cmdSetGatherPoint(msg)
    elseif a == "delete_unit" then return cmdDeleteUnit(msg)

    -- Game control
    elseif a == "set_camera" then
        if msg.x and msg.y then SetCameraPosition(Vector2(msg.x, msg.y)) end
        return { action = "ok" }
    elseif a == "chat" then
        if msg.message then SendChatMessage(tostring(msg.message)) end
        return { action = "ok" }
    elseif a == "pause" then
        SetGamePaused(true)
        return { action = "ok", paused = true }
    elseif a == "unpause" then
        SetGamePaused(false)
        return { action = "ok", paused = false }
    elseif a == "set_speed" then
        SetGameSpeedMultiplier(msg.speed or 1.0)
        return { action = "ok" }
    elseif a == "resign" then
        DispatchResignGame()
        return { action = "ok" }
    elseif a == "reload_module" then
        local pid = GetAssignedPlayerId()
        AssignAndLoadModule(pid, "aoe2bot")
        return { action = "ok", reloading = true }

    -- Affordability & pathfinding
    elseif a == "check_available" then
        local typeId, resolved = resolveBuildingType(msg.building_name or "")
        if not typeId then return { action = "error", error = "unknown: " .. (msg.building_name or "") } end
        local avail = IsObjectTypeAvailable(typeId)
        local afford = CanAfford(typeId, true)
        return { action = "available_result", building = resolved, typeId = typeId, available = avail, canAfford = afford }
    elseif a == "scan_available" then
        return cmdScanAvailable(msg)
    elseif a == "can_afford" then
        if msg.unit_type then
            return { action = "can_afford_result", can_afford = CanAfford(msg.unit_type, msg.is_building or false) }
        end
        return { action = "error", error = "missing unit_type" }
    elseif a == "find_path" then return cmdFindPath(msg)

    else
        return { action = "unknown", requested = a }
    end
end

-- ─── State Reading ──────────────────────────────────────────────────────────

function getState()
    local p = GetAssignedPlayer()
    if not p then
        return { action = "state", error = "no assigned player" }
    end

    local state = {
        action = "state",
        playerId = GetAssignedPlayerId(),
        time = GetGameTime(),
        paused = IsGamePaused(),
        helpersReady = helpersReady,
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
    if helpersReady and vilOccupation then
        pcall(function()
            state.occupation = {
                total = vilOccupation:GetVillagerCount(),
                idle = vilOccupation:GetIdleVillagerCount(),
            }
        end)
    end

    return state
end

function initHelpers()
    local ok, err = pcall(function()
        resourceTracker = ResourceTracker:new()
        vilOccupation = VillagerOccupation:new(resourceTracker)
        construction = ConstructionPlacement:new(vilOccupation)
        helpersReady = true
    end)
    if ok then
        return { action = "init_helpers_result", success = true, helpersReady = true }
    else
        return { action = "init_helpers_result", success = false, error = tostring(err) }
    end
end

function scanWorld(msg)
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

function scanResources()
    if not helpersReady or not resourceTracker then
        return { action = "error", error = "ResourceTracker not initialized" }
    end

    local result = { action = "resource_scan" }

    pcall(function()
        local trees = resourceTracker:GetTrees()
        result.treeCount = #trees
        result.trees = {}
        for i, t in ipairs(trees) do
            if i > 10 then break end
            local pos = t:GetPosition()
            table.insert(result.trees, { id = t:GetId(), x = pos.x, y = pos.y })
        end
    end)

    pcall(function()
        local gold = resourceTracker:GetGold()
        result.goldCount = #gold
        result.gold = {}
        for i, g in ipairs(gold) do
            if i > 10 then break end
            local pos = g:GetPosition()
            table.insert(result.gold, { id = g:GetId(), x = pos.x, y = pos.y })
        end
    end)

    pcall(function()
        local stone = resourceTracker:GetStone()
        result.stoneCount = #stone
        result.stone = {}
        for i, s in ipairs(stone) do
            if i > 10 then break end
            local pos = s:GetPosition()
            table.insert(result.stone, { id = s:GetId(), x = pos.x, y = pos.y })
        end
    end)

    pcall(function()
        local forage = resourceTracker:GetForage()
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

function scanLivestock()
    if not helpersReady or not resourceTracker then
        return { action = "error", error = "ResourceTracker not initialized" }
    end

    local result = { action = "livestock_scan", convertible = {}, owned = {} }

    pcall(function()
        local p = GetAssignedPlayer()
        if not p then return end
        local tcs = p:GetTownCenters()
        local tcPos = nil
        if #tcs > 0 then tcPos = tcs[1]:GetPosition() end

        local conv = resourceTracker:GetConvertibleLivestock(tcPos or Vector3(100,100,0), 100)
        for i, obj in ipairs(conv) do
            if i > 20 then break end
            local pos = obj:GetPosition()
            table.insert(result.convertible, { id = obj:GetId(), x = pos.x, y = pos.y })
        end

        local owned = resourceTracker:GetOwnedLivestock()
        for i, obj in ipairs(owned) do
            if i > 20 then break end
            local pos = obj:GetPosition()
            table.insert(result.owned, { id = obj:GetId(), x = pos.x, y = pos.y })
        end
    end)

    return result
end

function safeGetFact(fact, param)
    if fact == nil then return 0 end
    local ok, val
    if param ~= nil then
        ok, val = pcall(GetFact, fact, param)
    else
        ok, val = pcall(GetFact, fact)
    end
    return ok and val or 0
end

function getUnits(msg)
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

function getBuildings()
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

function getTownCenters()
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

function getMapTiles(msg)
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

function getPlayers()
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

function runDiagnostics()
    local diag = {
        action = "diagnostics",
        playerId = GetAssignedPlayerId(),
        time = GetGameTime(),
        helpersReady = helpersReady,
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
        resourceTracker = resourceTracker ~= nil,
        vilOccupation = vilOccupation ~= nil,
        construction = construction ~= nil,
    }
    if helpersReady and vilOccupation then
        pcall(function()
            diag.helpers.villagerCount = vilOccupation:GetVillagerCount()
            diag.helpers.idleCount = vilOccupation:GetIdleVillagerCount()
        end)
    end

    return diag
end

-- ─── Tech State / Building Counts / Vil Priorities ─────────────────────────

function cmdGetTechState(msg)
    local results = {}
    for _, techId in ipairs(msg.technologies or {}) do
        local entry = { researched = false, available = false }
        pcall(function() entry.researched = IsTechnologyResearched(techId) end)
        pcall(function() entry.available = CanResearch(techId) end)
        results[tostring(techId)] = entry
    end
    return { action = "tech_state", technologies = results }
end

function cmdGetBuildingCounts()
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

function cmdSetVilPriorities(msg)
    if not helpersReady or not vilOccupation then
        return { action = "error", error = "VillagerOccupation not initialized" }
    end
    local ok, err = pcall(function()
        vilOccupation:SetPriorities(msg.wood or 0, msg.food or 0, msg.gold or 0, msg.stone or 0)
        -- NOT calling vilOccupation:Update() — it auto-builds lumber camps/mills
        -- Python handles vil assignment directly via attack_target
    end)
    if ok then
        return { action = "vil_priorities_result", success = true }
    else
        return { action = "vil_priorities_result", success = false, error = tostring(err) }
    end
end

-- ─── Training Commands ──────────────────────────────────────────────────────

function cmdTrain(msg)
    local unitId = msg.unit_type
    local amount = msg.amount or 1
    if not unitId then return { action = "error", error = "missing unit_type" } end
    local ok = TrainUnit(unitId, amount)
    return { action = "train_result", success = ok, unit_type = unitId, amount = amount }
end

function cmdTrainByName(msg)
    local name = msg.unit_name
    if not name then return { action = "error", error = "missing unit_name" } end
    local typeId = UnitObjectType[name]
    if not typeId then return { action = "error", error = "unknown UnitObjectType: " .. name } end
    local amount = msg.amount or 1
    local ok = TrainUnit(typeId, amount)
    return { action = "train_result", success = ok, unit_name = name, unit_type = typeId, amount = amount }
end

-- ─── Raw Build Command ──────────────────────────────────────────────────────

function cmdBuild(msg)
    local structureId = msg.building_type
    local x, y = msg.x, msg.y
    if not structureId or not x or not y then
        return { action = "error", error = "missing building_type, x, or y" }
    end

    local builders = {}
    if msg.builder_ids then
        for _, bid in ipairs(msg.builder_ids) do
            local obj = GetObjectById(bid)
            if obj and obj:IsAlive() then table.insert(builders, obj) end
        end
    else
        pcall(function()
            local p = GetAssignedPlayer()
            local vils = p:GetObjectsByClass(UnitClass.VILLAGER)
            for _, v in ipairs(vils) do
                if v:IsAlive() and v:IsIdle() and v:GetOwningPlayer():GetId() == p:GetId() then
                    table.insert(builders, v)
                    break
                end
            end
        end)
    end

    if #builders == 0 then return { action = "error", error = "no builders available" } end

    local ok = UnitsBuildStructure(builders, structureId, Vector3(x, y, 0))
    return { action = "build_result", success = ok, building_type = structureId, x = x, y = y }
end

function cmdBuildByName(msg)
    local name = msg.building_name
    if not name then return { action = "error", error = "missing building_name" } end
    local typeId = UnitObjectType[name]
    if not typeId then return { action = "error", error = "unknown UnitObjectType: " .. name } end
    msg.building_type = typeId
    return cmdBuild(msg)
end

-- ─── Place Building (docs-faithful, minimal) ──────────────────────────────

function cmdPlaceBuilding(msg)
    local name = msg.building_name
    local x, y = msg.x, msg.y
    if not name or not x or not y then
        return { action = "error", error = "need building_name, x, y" }
    end

    -- 1. Find the enum
    local typeId, resolved = resolveBuildingType(name)
    if not typeId then
        return { action = "error", error = "unknown building: " .. name, step = 1 }
    end

    -- 2a. Check if type is available (prerequisites met)
    local available = IsObjectTypeAvailable(typeId)
    if not available then
        return { action = "error", error = "not available (prereqs): " .. resolved, step = 2, typeId = typeId }
    end

    -- 2b. Check resources
    local canAfford = CanAfford(typeId, true)
    if not canAfford then
        return { action = "error", error = "cannot afford " .. resolved, step = 2 }
    end

    -- 3. Use ConstructionPlacement to find valid position and build
    --    Skip for TC Foundation — both BuildStructure and FindBestPosition
    --    can hang or silently fail when no TC exists
    local isTCFoundation = (typeId == UnitObjectType["TOWN_CENTER_FOUNDATION"])
    if helpersReady and construction and not isTCFoundation then
        local buildOk, buildResult = pcall(function()
            return construction:BuildStructure(typeId, Vector3(x, y, 0), PlacementDirection.SOUTH_WEST, 1, true)
        end)
        if buildOk and buildResult then
            return {
                action = "place_building_result",
                success = true,
                building = resolved,
                buildable = true,
                builderCount = 0,
                method = "construction_helper",
                x = x, y = y, z = 0,
                step = 5,
            }
        end
        -- BuildStructure failed — fall through to manual method
    end

    -- 4. Manual fallback: find vils and use UnitsBuildStructure
    local p = GetAssignedPlayer()
    local allVils = {}
    for _, v in ipairs(p:GetObjectsByClass(UnitClass.VILLAGER)) do
        if v:IsAlive() and v:GetOwningPlayer():GetId() == p:GetId() then
            local pos = v:GetPosition()
            local dx = pos.x - x
            local dy = pos.y - y
            table.insert(allVils, { obj = v, dist = math.sqrt(dx*dx + dy*dy) })
        end
    end
    if #allVils == 0 then
        return { action = "error", error = "no villagers", step = 4 }
    end
    table.sort(allVils, function(a, b) return a.dist < b.dist end)
    local builders = {}
    local maxBuilders = isTCFoundation and #allVils or math.min(4, #allVils)
    for i = 1, maxBuilders do
        table.insert(builders, allVils[i].obj)
    end

    -- 4b. Find a valid position for the full building footprint
    local finalX, finalY, finalZ = x, y, 0

    if not isTCFoundation and helpersReady and construction then
        -- Non-TC: use FindBestPosition (works when TC exists)
        local findOk, bestPos = pcall(function()
            return construction:FindBestPosition(typeId, Vector3(x, y, 0), PlacementDirection.SOUTH_WEST, 1, true)
        end)
        if findOk and bestPos then
            finalX = bestPos.x
            finalY = bestPos.y
            finalZ = bestPos.z or 0
        end
    else
        -- TC Foundation: scan candidate positions, check full 4x4 footprint
        local function isFootprintClear(cx, cy, size)
            local half = math.floor(size / 2)
            for dx = -half, half do
                for dy = -half, half do
                    local tile = GetMapTile(math.floor(cx) + dx, math.floor(cy) + dy)
                    if not tile or not tile:IsBuildable() then
                        return false
                    end
                    -- Check for static objects (trees, berries, stone) blocking the tile
                    -- Skip mobile units (vils, scouts, livestock) — they move out of the way
                    local objs = tile:GetObjects()
                    if objs then
                        for _, obj in ipairs(objs) do
                            local cls = obj:GetClass()
                            -- 904=villager, 961=scout, 958=livestock — these move
                            if cls ~= 904 and cls ~= 961 and cls ~= 958 then
                                return false
                            end
                        end
                    end
                end
            end
            return true
        end

        local offsets = {
            {0, 0}, {3, 0}, {-3, 0}, {0, 3}, {0, -3},
            {3, 3}, {-3, 3}, {3, -3}, {-3, -3},
            {6, 0}, {-6, 0}, {0, 6}, {0, -6},
            {6, 3}, {-6, 3}, {6, -3}, {-6, -3},
            {3, 6}, {-3, 6}, {3, -6}, {-3, -6},
        }
        local found = false
        for _, off in ipairs(offsets) do
            local cx = x + off[1]
            local cy = y + off[2]
            if isFootprintClear(cx, cy, 4) then
                finalX = cx
                finalY = cy
                local tile = GetMapTile(math.floor(cx), math.floor(cy))
                if tile then finalZ = tile:GetElevation() end
                found = true
                break
            end
        end
        if not found then
            return { action = "error", error = "no clear 4x4 spot near " .. x .. "," .. y, step = 4 }
        end
    end

    -- 5. Place it
    local ok = UnitsBuildStructure(builders, typeId, Vector3(finalX, finalY, finalZ))
    return {
        action = "place_building_result",
        success = ok,
        building = resolved,
        x = finalX, y = finalY, z = finalZ,
        buildable = true,
        builderCount = #builders,
        method = isTCFoundation and "footprint_scan" or "find_best_position",
        step = 5,
    }
end

-- ─── Smart Build (ConstructionPlacement) ────────────────────────────────────

function cmdScanAvailable(msg)
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

function cmdAutoScout(msg)
    -- Try EnableScouting first (works for standard scout units)
    local ok = EnableScouting()
    if ok then
        return { action = "scout_result", success = true, method = "EnableScouting" }
    end

    -- Find any scout-class (961) unit and set auto-scout stance
    local p = GetAssignedPlayer()
    if not p then
        return { action = "scout_result", success = false, error = "no player" }
    end

    local scoutUnits = {}
    -- Try by specific unit ID if provided
    if msg and msg.unit_id then
        local obj = GetObjectById(msg.unit_id)
        if obj and obj:IsAlive() then
            table.insert(scoutUnits, obj)
        end
    end

    -- Otherwise scan all units for class 961 (cavalry scout line)
    if #scoutUnits == 0 then
        pcall(function()
            local allUnits = p:GetUnits()
            for _, u in ipairs(allUnits) do
                if u:IsAlive() and u:GetClass() == 961 then
                    table.insert(scoutUnits, u)
                end
            end
        end)
    end

    if #scoutUnits == 0 then
        return { action = "scout_result", success = false, error = "no scout units found" }
    end

    local stanceOk = false
    pcall(function()
        SetUnitStanceAutoScout(scoutUnits)
        stanceOk = true
    end)

    return { action = "scout_result", success = stanceOk, method = "SetUnitStanceAutoScout", count = #scoutUnits }
end

function resolveBuildingType(name)
    -- Special case: TC uses FOUNDATION for initial placement
    if name == "TOWN_CENTER" then
        local tcs = GetAssignedPlayer():GetTownCenters()
        if #tcs == 0 then
            local fId = UnitObjectType["TOWN_CENTER_FOUNDATION"]
            if fId then return fId, "TOWN_CENTER_FOUNDATION" end
        end
    end

    local typeId = UnitObjectType[name]
    if typeId then return typeId, name end

    local age = safeGetFact(Fact.CURRENT_AGE)
    local suffixes = { "_DARK_AGE", "_FEUDAL_AGE", "_CASTLE_AGE", "_IMPERIAL_AGE" }
    local ageSuffix = suffixes[age + 1] or "_DARK_AGE"

    typeId = UnitObjectType[name .. ageSuffix]
    if typeId then return typeId, name .. ageSuffix end

    for _, suf in ipairs(suffixes) do
        typeId = UnitObjectType[name .. suf]
        if typeId then return typeId, name .. suf end
    end

    return nil, name
end

function cmdSmartBuild(msg)
    if not helpersReady or not construction then
        return { action = "error", error = "ConstructionPlacement not initialized — check diagnostics" }
    end

    local name = msg.building_name
    if not name then return { action = "error", error = "missing building_name" } end

    local typeId, resolvedName = resolveBuildingType(name)
    if not typeId then return { action = "error", error = "unknown UnitObjectType: " .. name } end

    local padding = msg.padding or 1
    local ok = false
    local method = ""

    if msg.x and msg.y then
        local targetPos = Vector2(msg.x, msg.y)
        local p = GetAssignedPlayer()
        local vils = p:GetObjectsByClass(UnitClass.VILLAGER)
        local builderId = nil
        for _, v in ipairs(vils) do
            if v:IsAlive() and v:IsIdle() and v:GetOwningPlayer():GetId() == p:GetId() then
                builderId = v:GetId()
                break
            end
        end

        -- Try overloads in order of reliability
        local attempts = {
            { name = "BuildStructure(builder,pos,dir,pad,bypass)",
              fn = function() return construction:BuildStructure(typeId, builderId, targetPos, PlacementDirection.SouthWest, padding, true) end },
            { name = "BuildStructure(builder,pos,dir,pad)",
              fn = function() return construction:BuildStructure(typeId, builderId, targetPos, PlacementDirection.SouthWest, padding) end },
            { name = "BuildStructure(pos,dir,pad,bypass)",
              fn = function() return construction:BuildStructure(typeId, targetPos, PlacementDirection.SouthWest, padding, true) end },
            { name = "BuildStructure(pos,dir,pad)",
              fn = function() return construction:BuildStructure(typeId, targetPos, PlacementDirection.SouthWest, padding) end },
        }
        for _, attempt in ipairs(attempts) do
            local tryOk, tryResult = pcall(attempt.fn)
            if tryOk and tryResult then
                ok = true
                method = attempt.name
                break
            elseif tryOk then
                method = attempt.name .. "(returned false)"
            end
        end
    else
        -- Auto-place near TC
        local tcs = GetAssignedPlayer():GetTownCenters()
        if #tcs > 0 then
            ok = construction:BuildStructureAtTown(typeId, padding)
            method = "BuildStructureAtTown(auto)"
        else
            -- No TC: find vils, pick average position, try all overloads
            local p = GetAssignedPlayer()
            local vils = p:GetObjectsByClass(UnitClass.VILLAGER)
            local sumX, sumY, count = 0, 0, 0
            local builderId = nil
            for _, v in ipairs(vils) do
                if v:IsAlive() and v:GetOwningPlayer():GetId() == p:GetId() then
                    local pos = v:GetPosition()
                    sumX = sumX + pos.x
                    sumY = sumY + pos.y
                    count = count + 1
                    if not builderId and v:IsIdle() then
                        builderId = v:GetId()
                    end
                end
            end
            if count > 0 then
                local avgPos = Vector2(sumX / count, sumY / count)
                local attempts = {
                    { name = "BuildStructure(builder,vilAvg,dir,pad,bypass)",
                      fn = function() return construction:BuildStructure(typeId, builderId, avgPos, PlacementDirection.SouthWest, padding, true) end },
                    { name = "BuildStructure(vilAvg,dir,pad,bypass)",
                      fn = function() return construction:BuildStructure(typeId, avgPos, PlacementDirection.SouthWest, padding, true) end },
                    { name = "BuildStructure(vilAvg,dir,pad)",
                      fn = function() return construction:BuildStructure(typeId, avgPos, PlacementDirection.SouthWest, padding) end },
                }
                for _, attempt in ipairs(attempts) do
                    local tryOk, tryResult = pcall(attempt.fn)
                    if tryOk and tryResult then
                        ok = true
                        method = attempt.name
                        break
                    end
                end
            end
        end
    end

    return {
        action = "smart_build_result",
        success = ok,
        building = resolvedName,
        method = method,
    }
end

function cmdFindPlacement(msg)
    if not helpersReady or not construction then
        return { action = "error", error = "ConstructionPlacement not initialized" }
    end

    local name = msg.building_name
    if not name then return { action = "error", error = "missing building_name" } end

    local typeId = resolveBuildingType(name)
    if not typeId then return { action = "error", error = "unknown UnitObjectType: " .. name } end

    local padding = msg.padding or 1

    if name == "FARM" then
        local ok, tile = pcall(function() return construction:GetValidFarmPlacementTile() end)
        if ok and tile then
            local pos = tile:GetPosition()
            return {
                action = "placement_result",
                building = name,
                x = pos.x, y = pos.y,
                buildable = tile:IsBuildable(),
            }
        end
        return { action = "placement_result", building = name, found = false }
    end

    local targetPos
    if msg.x and msg.y then
        targetPos = Vector2(msg.x, msg.y)
    else
        -- Default to TC position
        local tcs = GetAssignedPlayer():GetTownCenters()
        if #tcs > 0 then
            targetPos = Vector2(tcs[1]:GetPosition().x, tcs[1]:GetPosition().y)
        else
            return { action = "error", error = "no target position and no TC found" }
        end
    end

    local ok, pos = pcall(function()
        return construction:FindBestPosition(typeId, targetPos, PlacementDirection.SOUTH_WEST, padding, false)
    end)

    if ok and pos then
        return {
            action = "placement_result",
            building = name,
            x = pos.x, y = pos.y,
            found = true,
        }
    end

    return { action = "placement_result", building = name, found = false }
end

function cmdQueueBuild(msg)
    if not helpersReady or not construction then
        return { action = "error", error = "ConstructionPlacement not initialized" }
    end

    local name = msg.building_name
    if not name then return { action = "error", error = "missing building_name" } end

    local typeId = resolveBuildingType(name)
    if not typeId then return { action = "error", error = "unknown UnitObjectType: " .. name } end

    local priority = msg.priority or 5
    local padding = msg.padding or 1

    local already = construction:IsStructureTypeQueued(typeId)
    if already then
        return { action = "queue_build_result", success = false, building = name, reason = "already queued" }
    end

    pcall(function()
        construction:QueueBuildingRequestAtTown(typeId, priority, padding, false, nil, false)
    end)

    return { action = "queue_build_result", success = true, building = name, priority = priority }
end

function cmdGetFarmPlacement()
    if not helpersReady or not construction then
        return { action = "error", error = "ConstructionPlacement not initialized" }
    end

    local ok, tile = pcall(function() return construction:GetValidFarmPlacementTile() end)
    if ok and tile then
        local pos = tile:GetPosition()
        return { action = "farm_placement", x = pos.x, y = pos.y, buildable = tile:IsBuildable() }
    end
    return { action = "farm_placement", found = false }
end

-- ─── Research ───────────────────────────────────────────────────────────────

function cmdResearch(msg)
    local techId = msg.technology
    if not techId then return { action = "error", error = "missing technology" } end
    local ok = ResearchTechnology(techId)
    return { action = "research_result", success = ok, technology = techId }
end

function cmdResearchByName(msg)
    local name = msg.tech_name
    if not name then return { action = "error", error = "missing tech_name" } end
    local techId = Technology[name]
    if not techId then return { action = "error", error = "unknown Technology: " .. name } end
    local ok = ResearchTechnology(techId)
    return { action = "research_result", success = ok, tech_name = name, technology = techId }
end

-- ─── Unit Commands ──────────────────────────────────────────────────────────

function cmdMove(msg)
    if not msg.unit_ids or not msg.x or not msg.y then
        return { action = "error", error = "missing unit_ids, x, or y" }
    end
    local units = resolveUnits(msg.unit_ids)
    if #units == 0 then return { action = "error", error = "no valid units" } end
    local ok = UnitsMove(units, Vector3(msg.x, msg.y, 0))
    return { action = "move_result", success = ok, count = #units }
end

function cmdAttack(msg)
    if not msg.unit_ids or not msg.target_id then
        return { action = "error", error = "missing unit_ids or target_id" }
    end
    local units = resolveUnits(msg.unit_ids)
    local target = GetObjectById(msg.target_id)
    if #units == 0 or not target then return { action = "error", error = "invalid units or target" } end
    local ok = UnitsTargetObject(units, target)
    return { action = "attack_result", success = ok, count = #units }
end

function cmdAttackMove(msg)
    if not msg.unit_ids or not msg.x or not msg.y then
        return { action = "error", error = "missing unit_ids, x, or y" }
    end
    local units = resolveUnits(msg.unit_ids)
    if #units == 0 then return { action = "error", error = "no valid units" } end
    SetUnitStanceAttackMove(units, Vector3(msg.x, msg.y, 0))
    return { action = "attack_move_result", success = true, count = #units }
end

function cmdPatrol(msg)
    if not msg.unit_ids or not msg.x or not msg.y then
        return { action = "error", error = "missing fields" }
    end
    local units = resolveUnits(msg.unit_ids)
    SetUnitStancePatrol(units, Vector3(msg.x, msg.y, 0))
    return { action = "patrol_result", success = true, count = #units }
end

function cmdGarrison(msg)
    if not msg.unit_ids or not msg.target_id then
        return { action = "error", error = "missing fields" }
    end
    local units = resolveUnits(msg.unit_ids)
    local target = GetObjectById(msg.target_id)
    if #units == 0 or not target then return { action = "error", error = "invalid units or target" } end
    SetUnitStanceGarrison(units, target)
    return { action = "garrison_result", success = true }
end

function cmdSetStance(msg)
    if not msg.unit_ids or msg.stance == nil then
        return { action = "error", error = "missing fields" }
    end
    local units = resolveUnits(msg.unit_ids)
    SetUnitCombatStance(units, msg.stance)
    return { action = "stance_result", success = true, count = #units }
end

function cmdSetGatherPoint(msg)
    if not msg.building_ids or not msg.x or not msg.y then
        return { action = "error", error = "missing fields" }
    end
    local buildings = resolveUnits(msg.building_ids)
    SetGatherPoint(buildings, Vector3(msg.x, msg.y, 0))
    return { action = "gather_point_result", success = true }
end

function cmdDeleteUnit(msg)
    if not msg.unit_id then return { action = "error", error = "missing unit_id" } end
    local unit = GetObjectById(msg.unit_id)
    if not unit then return { action = "error", error = "unit not found" } end
    DeleteUnit(unit)
    return { action = "delete_result", success = true }
end

function cmdFindPath(msg)
    if not msg.x1 or not msg.y1 or not msg.x2 or not msg.y2 then
        return { action = "error", error = "missing coordinates" }
    end
    local path = CalculatePath(Vector3(msg.x1, msg.y1, 0), Vector3(msg.x2, msg.y2, 0))
    local points = {}
    for _, pt in ipairs(path) do
        table.insert(points, { x = pt.x, y = pt.y, z = pt.z })
    end
    return { action = "path_result", count = #points, path = points }
end

-- ─── Helpers ────────────────────────────────────────────────────────────────

function resolveUnits(unitIds)
    local units = {}
    for _, id in ipairs(unitIds) do
        local ok, obj = pcall(GetObjectById, id)
        if ok and obj and obj:IsAlive() then table.insert(units, obj) end
    end
    return units
end

function enumLookup(msg)
    local table_name = msg.table_name
    if not table_name then return { action = "error", error = "missing table_name" } end

    local t = _G[table_name]
    if not t or type(t) ~= "table" then
        return { action = "error", error = "unknown enum table: " .. tostring(table_name) }
    end

    if msg.key then
        return { action = "enum_result", table_name = table_name, key = msg.key, value = t[msg.key] }
    end

    if msg.search then
        local results = {}
        local pat = string.upper(msg.search)
        for k, v in pairs(t) do
            if string.find(string.upper(k), pat) then results[k] = v end
        end
        return { action = "enum_result", table_name = table_name, search = msg.search, results = results }
    end

    local results = {}
    local count = 0
    for k, v in pairs(t) do
        if count < 50 then results[k] = v; count = count + 1 end
    end
    return { action = "enum_result", table_name = table_name, count = count, results = results }
end
