-- AoE2Bot command handlers
-- All actions that mutate game state: building, training, research, unit orders, etc.

local commands = {}

-- Module-level references set by main.lua after require
commands.helpersReady = false
commands.resourceTracker = nil
commands.vilOccupation = nil
commands.construction = nil
commands.util = nil  -- set by main.lua

-- ─── Training Commands ──────────────────────────────────────────────────────

function commands.cmdTrain(msg)
    local unitId = msg.unit_type
    local amount = msg.amount or 1
    if not unitId then return { action = "error", error = "missing unit_type" } end
    local ok = TrainUnit(unitId, amount)
    return { action = "train_result", success = ok, unit_type = unitId, amount = amount }
end

function commands.cmdTrainByName(msg)
    local name = msg.unit_name
    if not name then return { action = "error", error = "missing unit_name" } end
    local typeId = UnitObjectType[name]
    if not typeId then return { action = "error", error = "unknown UnitObjectType: " .. name } end
    local amount = msg.amount or 1
    local ok = TrainUnit(typeId, amount)
    return { action = "train_result", success = ok, unit_name = name, unit_type = typeId, amount = amount }
end

-- ─── Raw Build Command ──────────────────────────────────────────────────────

function commands.cmdBuild(msg)
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

function commands.cmdBuildByName(msg)
    local name = msg.building_name
    if not name then return { action = "error", error = "missing building_name" } end
    local typeId = UnitObjectType[name]
    if not typeId then return { action = "error", error = "unknown UnitObjectType: " .. name } end
    msg.building_type = typeId
    return commands.cmdBuild(msg)
end

-- ─── Place Building (docs-faithful, minimal) ──────────────────────────────

function commands.cmdPlaceBuilding(msg)
    local resolveBuildingType = commands.util.resolveBuildingType

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
    local isFarm = (resolved == "FARM" or resolved == "FARM_DARK_AGE" or resolved == "FARM_FEUDAL_AGE" or resolved == "FARM_CASTLE_AGE" or resolved == "FARM_IMPERIAL_AGE")

    -- Farms: use GetValidFarmPlacementTile for correct snapped positioning
    if isFarm and commands.helpersReady and commands.construction then
        local tileOk, tile = pcall(function()
            return commands.construction:GetValidFarmPlacementTile()
        end)
        if tileOk and tile then
            local farmOk, farmResult = pcall(function()
                return commands.construction:BuildStructure(typeId, Vector3(tile.x, tile.y, 0), PlacementDirection.SOUTH_WEST, 0, true)
            end)
            if farmOk and farmResult then
                return {
                    action = "place_building_result",
                    success = true,
                    building = resolved,
                    buildable = true,
                    builderCount = 0,
                    method = "farm_placement",
                    x = tile.x, y = tile.y, z = 0,
                    step = 5,
                }
            end
        end
        -- Fall through to manual method if farm placement fails
    end

    -- Non-farm, non-TC: use BuildStructure (skip if caller specified builder_ids)
    if not isTCFoundation and not isFarm and not msg.builder_ids and commands.helpersReady and commands.construction then
        local buildOk, buildResult = pcall(function()
            return commands.construction:BuildStructure(typeId, Vector3(x, y, 0), PlacementDirection.SOUTH_WEST, 1, true)
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

    -- 4. Find builders — use specific builder_ids if provided, else closest vils
    local builders = {}
    if msg.builder_ids then
        for _, bid in ipairs(msg.builder_ids) do
            local obj = GetObjectById(bid)
            if obj and obj:IsAlive() then table.insert(builders, obj) end
        end
    else
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
        local maxBuilders = isTCFoundation and #allVils or math.min(4, #allVils)
        for i = 1, maxBuilders do
            table.insert(builders, allVils[i].obj)
        end
    end
    if #builders == 0 then
        return { action = "error", error = "no builders", step = 4 }
    end

    -- 4b. Find a clear spot for the building footprint
    --     ALL buildings get footprint scanned — no silent failures on trees/objects
    --     TC=4x4, most buildings=2x2, houses=2x2
    local bSize = isTCFoundation and 4 or 2
    local finalX, finalY, finalZ = x, y, 0

    local function isFootprintClear(cx, cy, size)
        local half = math.floor(size / 2)
        for dx = -half, half - 1 do
            for dy = -half, half - 1 do
                local tile = GetMapTile(math.floor(cx) + dx, math.floor(cy) + dy)
                if not tile then return false end
                -- IsBuildable checks flat terrain, IsWalkable catches trees/obstacles
                local buildable = false
                local walkable = false
                pcall(function() buildable = tile:IsBuildable() end)
                pcall(function() walkable = tile:IsWalkable() end)
                if not buildable or not walkable then
                    return false
                end
                -- Double-check for visible objects (resources, buildings)
                local objCount = 0
                pcall(function() objCount = tile:GetObjectCount() end)
                if objCount > 0 then
                    local hasBlocker = false
                    pcall(function()
                        local objs = tile:GetObjects()
                        for _, obj in ipairs(objs) do
                            local clsOk, cls = pcall(function() return obj:GetClass() end)
                            if clsOk and cls ~= 904 and cls ~= 961 and cls ~= 958 then
                                hasBlocker = true
                            end
                        end
                    end)
                    if hasBlocker then return false end
                end
            end
        end
        return true
    end

    local offsets = {
        {0, 0}, {2, 0}, {-2, 0}, {0, 2}, {0, -2},
        {2, 2}, {-2, 2}, {2, -2}, {-2, -2},
        {4, 0}, {-4, 0}, {0, 4}, {0, -4},
        {4, 2}, {-4, 2}, {4, -2}, {-4, -2},
        {2, 4}, {-2, 4}, {2, -4}, {-2, -4},
        {6, 0}, {-6, 0}, {0, 6}, {0, -6},
        {6, 2}, {-6, 2}, {6, -2}, {-6, -2},
    }
    local found = false
    for _, off in ipairs(offsets) do
        local cx = x + off[1]
        local cy = y + off[2]
        if isFootprintClear(cx, cy, bSize) then
            finalX = cx
            finalY = cy
            local tile = GetMapTile(math.floor(cx), math.floor(cy))
            if tile then finalZ = tile:GetElevation() end
            found = true
            break
        end
    end
    if not found then
        return { action = "error", error = "no clear spot near " .. x .. "," .. y .. " (size=" .. bSize .. ")", step = 4 }
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

function commands.cmdSmartBuild(msg)
    local resolveBuildingType = commands.util.resolveBuildingType

    if not commands.helpersReady or not commands.construction then
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
              fn = function() return commands.construction:BuildStructure(typeId, builderId, targetPos, PlacementDirection.SouthWest, padding, true) end },
            { name = "BuildStructure(builder,pos,dir,pad)",
              fn = function() return commands.construction:BuildStructure(typeId, builderId, targetPos, PlacementDirection.SouthWest, padding) end },
            { name = "BuildStructure(pos,dir,pad,bypass)",
              fn = function() return commands.construction:BuildStructure(typeId, targetPos, PlacementDirection.SouthWest, padding, true) end },
            { name = "BuildStructure(pos,dir,pad)",
              fn = function() return commands.construction:BuildStructure(typeId, targetPos, PlacementDirection.SouthWest, padding) end },
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
            ok = commands.construction:BuildStructureAtTown(typeId, padding)
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
                      fn = function() return commands.construction:BuildStructure(typeId, builderId, avgPos, PlacementDirection.SouthWest, padding, true) end },
                    { name = "BuildStructure(vilAvg,dir,pad,bypass)",
                      fn = function() return commands.construction:BuildStructure(typeId, avgPos, PlacementDirection.SouthWest, padding, true) end },
                    { name = "BuildStructure(vilAvg,dir,pad)",
                      fn = function() return commands.construction:BuildStructure(typeId, avgPos, PlacementDirection.SouthWest, padding) end },
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

function commands.cmdFindPlacement(msg)
    local resolveBuildingType = commands.util.resolveBuildingType

    if not commands.helpersReady or not commands.construction then
        return { action = "error", error = "ConstructionPlacement not initialized" }
    end

    local name = msg.building_name
    if not name then return { action = "error", error = "missing building_name" } end

    local typeId = resolveBuildingType(name)
    if not typeId then return { action = "error", error = "unknown UnitObjectType: " .. name } end

    local padding = msg.padding or 1

    if name == "FARM" then
        local ok, tile = pcall(function() return commands.construction:GetValidFarmPlacementTile() end)
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
        return commands.construction:FindBestPosition(typeId, targetPos, PlacementDirection.SOUTH_WEST, padding, false)
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

function commands.cmdQueueBuild(msg)
    local resolveBuildingType = commands.util.resolveBuildingType

    if not commands.helpersReady or not commands.construction then
        return { action = "error", error = "ConstructionPlacement not initialized" }
    end

    local name = msg.building_name
    if not name then return { action = "error", error = "missing building_name" } end

    local typeId = resolveBuildingType(name)
    if not typeId then return { action = "error", error = "unknown UnitObjectType: " .. name } end

    local priority = msg.priority or 5
    local padding = msg.padding or 1

    local already = commands.construction:IsStructureTypeQueued(typeId)
    if already then
        return { action = "queue_build_result", success = false, building = name, reason = "already queued" }
    end

    pcall(function()
        commands.construction:QueueBuildingRequestAtTown(typeId, priority, padding, false, nil, false)
    end)

    return { action = "queue_build_result", success = true, building = name, priority = priority }
end

function commands.cmdGetFarmPlacement()
    if not commands.helpersReady or not commands.construction then
        return { action = "error", error = "ConstructionPlacement not initialized" }
    end

    local ok, tile = pcall(function() return commands.construction:GetValidFarmPlacementTile() end)
    if ok and tile then
        local pos = tile:GetPosition()
        return { action = "farm_placement", x = pos.x, y = pos.y, buildable = tile:IsBuildable() }
    end
    return { action = "farm_placement", found = false }
end

-- ─── Research ───────────────────────────────────────────────────────────────

function commands.cmdResearch(msg)
    local techId = msg.technology
    if not techId then return { action = "error", error = "missing technology" } end
    local ok = ResearchTechnology(techId)
    return { action = "research_result", success = ok, technology = techId }
end

function commands.cmdResearchByName(msg)
    local name = msg.tech_name
    if not name then return { action = "error", error = "missing tech_name" } end
    local techId = Technology[name]
    if not techId then return { action = "error", error = "unknown Technology: " .. name } end
    local ok = ResearchTechnology(techId)
    return { action = "research_result", success = ok, tech_name = name, technology = techId }
end

-- ─── Unit Commands ──────────────────────────────────────────────────────────

function commands.cmdMove(msg)
    local resolveUnits = commands.util.resolveUnits

    if not msg.unit_ids or not msg.x or not msg.y then
        return { action = "error", error = "missing unit_ids, x, or y" }
    end
    local units = resolveUnits(msg.unit_ids)
    if #units == 0 then return { action = "error", error = "no valid units" } end
    local ok = UnitsMove(units, Vector3(msg.x, msg.y, 0))
    return { action = "move_result", success = ok, count = #units }
end

function commands.cmdAttack(msg)
    local resolveUnits = commands.util.resolveUnits

    if not msg.unit_ids or not msg.target_id then
        return { action = "error", error = "missing unit_ids or target_id" }
    end
    local units = resolveUnits(msg.unit_ids)
    local target = GetObjectById(msg.target_id)
    if #units == 0 or not target then return { action = "error", error = "invalid units or target" } end
    local ok = UnitsTargetObject(units, target)
    return { action = "attack_result", success = ok, count = #units }
end

function commands.cmdAttackMove(msg)
    local resolveUnits = commands.util.resolveUnits

    if not msg.unit_ids or not msg.x or not msg.y then
        return { action = "error", error = "missing unit_ids, x, or y" }
    end
    local units = resolveUnits(msg.unit_ids)
    if #units == 0 then return { action = "error", error = "no valid units" } end
    SetUnitStanceAttackMove(units, Vector3(msg.x, msg.y, 0))
    return { action = "attack_move_result", success = true, count = #units }
end

function commands.cmdPatrol(msg)
    local resolveUnits = commands.util.resolveUnits

    if not msg.unit_ids or not msg.x or not msg.y then
        return { action = "error", error = "missing fields" }
    end
    local units = resolveUnits(msg.unit_ids)
    SetUnitStancePatrol(units, Vector3(msg.x, msg.y, 0))
    return { action = "patrol_result", success = true, count = #units }
end

function commands.cmdGarrison(msg)
    local resolveUnits = commands.util.resolveUnits

    if not msg.unit_ids or not msg.target_id then
        return { action = "error", error = "missing fields" }
    end
    local units = resolveUnits(msg.unit_ids)
    local target = GetObjectById(msg.target_id)
    if #units == 0 or not target then return { action = "error", error = "invalid units or target" } end
    SetUnitStanceGarrison(units, target)
    return { action = "garrison_result", success = true }
end

function commands.cmdAutoScout(msg)
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

function commands.cmdSetStance(msg)
    local resolveUnits = commands.util.resolveUnits

    if not msg.unit_ids or msg.stance == nil then
        return { action = "error", error = "missing fields" }
    end
    local units = resolveUnits(msg.unit_ids)
    SetUnitCombatStance(units, msg.stance)
    return { action = "stance_result", success = true, count = #units }
end

function commands.cmdSetGatherPoint(msg)
    local resolveUnits = commands.util.resolveUnits

    if not msg.building_ids or not msg.x or not msg.y then
        return { action = "error", error = "missing fields" }
    end
    local buildings = resolveUnits(msg.building_ids)
    SetGatherPoint(buildings, Vector3(msg.x, msg.y, 0))
    return { action = "gather_point_result", success = true }
end

function commands.cmdDeleteUnit(msg)
    if not msg.unit_id then return { action = "error", error = "missing unit_id" } end
    local unit = GetObjectById(msg.unit_id)
    if not unit then return { action = "error", error = "unit not found" } end
    DeleteUnit(unit)
    return { action = "delete_result", success = true }
end

function commands.cmdFindPath(msg)
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

function commands.cmdSetVilPriorities(msg)
    if not commands.helpersReady or not commands.vilOccupation then
        return { action = "error", error = "VillagerOccupation not initialized" }
    end
    local ok, err = pcall(function()
        commands.vilOccupation:SetPriorities(msg.wood or 0, msg.food or 0, msg.gold or 0, msg.stone or 0)
        -- NOT calling vilOccupation:Update() — it auto-builds lumber camps/mills
        -- Python handles vil assignment directly via attack_target
    end)
    if ok then
        return { action = "vil_priorities_result", success = true }
    else
        return { action = "vil_priorities_result", success = false, error = tostring(err) }
    end
end

return commands
