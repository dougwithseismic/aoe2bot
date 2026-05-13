-- AoE2Bot Bridge Module for AoE2Control
-- Exposes game state and command execution via named pipe IPC.
-- Uses ResourceTracker, VillagerOccupation, and ConstructionPlacement helpers.

local util = require("util")
local queries = require("queries")
local commands = require("commands")

local PIPE_NAME = "AoE2Bot_Pipe"
local pipe_connected = false

local resourceTracker = nil
local vilOccupation = nil
local construction = nil
local helpersReady = false

-- Propagate shared state to submodules
local function syncGlobals()
    queries.helpersReady = helpersReady
    queries.resourceTracker = resourceTracker
    queries.vilOccupation = vilOccupation
    queries.construction = construction
    queries.util = util

    commands.helpersReady = helpersReady
    commands.resourceTracker = resourceTracker
    commands.vilOccupation = vilOccupation
    commands.construction = construction
    commands.util = util
end

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
        -- Skip VillagerOccupation — it auto-assigns all vils on creation,
        -- sending livestock running across the map on Nomad starts
        construction = ConstructionPlacement:new()
        helpersReady = true
    end)
    if ok then
        Log("[AoE2Bot] Helpers initialized (ResourceTracker, ConstructionPlacement)")
    else
        Log("[AoE2Bot] WARNING: Helper init failed: " .. tostring(err))
        helpersReady = false
    end

    syncGlobals()
end

function Update()
    if helpersReady then
        pcall(function() resourceTracker:Update() end)
        -- NOT calling vilOccupation:Update() — it hijacks all vil assignments
        -- NOT calling construction:Update() or ProcessBuildingRequests()
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

-- ─── Helper Re-init (called via IPC) ────────────────────────────────────────

local function initHelpers()
    local ok, err = pcall(function()
        resourceTracker = ResourceTracker:new()
        vilOccupation = VillagerOccupation:new(resourceTracker)
        construction = ConstructionPlacement:new(vilOccupation)
        helpersReady = true
    end)
    syncGlobals()
    if ok then
        return { action = "init_helpers_result", success = true, helpersReady = true }
    else
        return { action = "init_helpers_result", success = false, error = tostring(err) }
    end
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
    elseif a == "get_state" then return queries.getState()
    elseif a == "get_units" then return queries.getUnits(msg)
    elseif a == "get_buildings" then return queries.getBuildings()
    elseif a == "get_town_centers" then return queries.getTownCenters()
    elseif a == "get_map" then
        return { action = "map_info", width = GetMapWidth(), height = GetMapHeight(), time = GetGameTime() }
    elseif a == "get_map_tiles" then return queries.getMapTiles(msg)
    elseif a == "get_players" then return queries.getPlayers()
    elseif a == "scan_world" then return queries.scanWorld(msg)
    elseif a == "scan_resources" then return queries.scanResources()
    elseif a == "scan_livestock" then return queries.scanLivestock()
    elseif a == "diag" then return queries.runDiagnostics()
    elseif a == "enum_lookup" then return util.enumLookup(msg)
    elseif a == "get_tech_state" then return queries.cmdGetTechState(msg)
    elseif a == "get_building_counts" then return queries.cmdGetBuildingCounts()
    elseif a == "set_vil_priorities" then return commands.cmdSetVilPriorities(msg)

    -- Training
    elseif a == "train" then return commands.cmdTrain(msg)
    elseif a == "train_by_name" then return commands.cmdTrainByName(msg)

    -- Building (raw)
    elseif a == "build" then return commands.cmdBuild(msg)
    elseif a == "build_by_name" then return commands.cmdBuildByName(msg)
    elseif a == "place_building" then return commands.cmdPlaceBuilding(msg)

    -- Smart building (ConstructionPlacement)
    elseif a == "smart_build" then return commands.cmdSmartBuild(msg)
    elseif a == "find_placement" then return commands.cmdFindPlacement(msg)
    elseif a == "queue_build" then return commands.cmdQueueBuild(msg)
    elseif a == "get_farm_placement" then return commands.cmdGetFarmPlacement()

    -- Research
    elseif a == "research" then return commands.cmdResearch(msg)
    elseif a == "research_by_name" then return commands.cmdResearchByName(msg)

    -- Unit commands
    elseif a == "move" then return commands.cmdMove(msg)
    elseif a == "attack" then return commands.cmdAttack(msg)
    elseif a == "attack_move" then return commands.cmdAttackMove(msg)
    elseif a == "patrol" then return commands.cmdPatrol(msg)
    elseif a == "garrison" then return commands.cmdGarrison(msg)
    elseif a == "scout" then return commands.cmdAutoScout(msg)
    elseif a == "set_stance" then return commands.cmdSetStance(msg)
    elseif a == "set_gather_point" then return commands.cmdSetGatherPoint(msg)
    elseif a == "delete_unit" then return commands.cmdDeleteUnit(msg)

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
        local typeId, resolved = util.resolveBuildingType(msg.building_name or "")
        if not typeId then return { action = "error", error = "unknown: " .. (msg.building_name or "") } end
        local avail = IsObjectTypeAvailable(typeId)
        local afford = CanAfford(typeId, true)
        return { action = "available_result", building = resolved, typeId = typeId, available = avail, canAfford = afford }
    elseif a == "scan_available" then
        return queries.cmdScanAvailable(msg)
    elseif a == "can_afford" then
        if msg.unit_type then
            return { action = "can_afford_result", can_afford = CanAfford(msg.unit_type, msg.is_building or false) }
        end
        return { action = "error", error = "missing unit_type" }
    elseif a == "find_path" then return commands.cmdFindPath(msg)

    else
        return { action = "unknown", requested = a }
    end
end
