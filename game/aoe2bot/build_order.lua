-- 22-Pop Scout Rush Build Order
-- Priority-based state machine: critical actions first, then build order steps.
-- Buildings use state tracking (none → ordered → done) verified against the map.

local h = require("helpers")
local event_log = require("event_log")

local bo = {}

local TECH_LOOM = 22
local TECH_FEUDAL = 101
local TECH_DOUBLE_BIT_AXE = 202
local TECH_HORSE_COLLAR = 14

local ORDERED_TIMEOUT = 120

local state = {}
local rt = nil

function bo.init(resource_tracker)
    rt = resource_tracker
    state = {
        tick = 0,
        scouting = false,
        wood_target = nil,
        food_forced = false,
        feudal_clicked = false,
        loom_done = false,
        lc = "none",
        mill = "none",
        mc = "none",
        barracks = "none",
        range = "none",
        lc_ordered_at = 0,
        mill_ordered_at = 0,
        mc_ordered_at = 0,
        barracks_ordered_at = 0,
        range_ordered_at = 0,
        houses_pending = 0,
        houses_seen = 0,
    }
end

-- ── Building State Checks ──

local function sync_building(key, pattern)
    if state[key] == "done" then return "done" end
    if #h.buildings(pattern) > 0 then
        state[key] = "done"
        return "done"
    end
    if state[key] == "ordered" then
        local ordered_at = state[key .. "_ordered_at"] or 0
        if state.tick - ordered_at > ORDERED_TIMEOUT then
            state[key] = "none"
            return "none"
        end
    end
    return state[key]
end

-- ── Priority Actions (always checked) ──

local function ensure_scouting()
    if state.scouting then return false end
    state.scouting = true
    return h.auto_scout()
end

local function ensure_houses()
    local pop = h.pop()
    local built_houses = #h.buildings("HOUSE")
    if built_houses < state.houses_seen then
        state.houses_pending = 0
    elseif built_houses > state.houses_seen then
        state.houses_pending = math.max(0, state.houses_pending - (built_houses - state.houses_seen))
    end
    state.houses_seen = built_houses
    local tcs = h.tcs()
    local housing_have = (built_houses + state.houses_pending) * 5 + #tcs * 5
    if housing_have >= pop.current + 4 then return false end
    if not h.can_afford(0, 25, 0, 0) then return false end
    local ok = h.build_near_tc("HOUSE_DARK_AGE")
    if ok then state.houses_pending = state.houses_pending + 1 end
    return ok
end

local function ensure_training()
    local pop = h.pop()
    local built_houses = #h.buildings("HOUSE")
    local tcs = h.tcs()
    local housing = built_houses * 5 + #tcs * 5
    if pop.current >= housing then return false end
    if not h.can_afford(50, 0, 0, 0) then return false end
    if #tcs == 0 then return false end
    local ok, idle = pcall(function() return tcs[1]:IsIdle() end)
    if not ok or not idle then return false end
    return h.train_vil()
end

-- ── Resource Helpers ──

local function refresh_wood_target()
    if not rt then return end
    if state.wood_target then
        local ok, alive = pcall(function() return state.wood_target:IsAlive() end)
        if ok and alive then return end
    end
    local tree = h.find_trees_near_lc(rt)
    if tree then
        state.wood_target = tree
        return
    end
    local tc = h.tc_pos()
    if tc then state.wood_target = h.find_safe_trees(rt, tc) end
end

local function assign_to_food(vils)
    local tc = h.tc_pos()
    if not tc then return false end
    local food = h.find_food(rt, tc)
    if not food then return false end
    return h.gather(vils, food)
end

local function assign_to_wood(vils)
    refresh_wood_target()
    if not state.wood_target then return false end
    return h.gather(vils, state.wood_target)
end

local function assign_to_gold(vils)
    local tc = h.tc_pos()
    if not tc then return false end
    local gold = h.find_gold(rt, tc)
    if not gold then return false end
    return h.gather(vils, gold)
end

-- ── Build Order Steps ──

local function force_initial_food()
    if state.food_forced then return false end
    if state.tick > 10 then state.food_forced = true; return false end
    local idle = h.idle_vils()
    if #idle == 0 then state.food_forced = true; return false end
    local ok = assign_to_food(idle)
    if ok then
        state.food_forced = true
        event_log.add("idle vils -> food (" .. #idle .. " vils)")
    end
    return ok
end

local function ensure_farms()
    local pop = h.pop()
    if pop.vils < 12 then return false end
    local current_farms = h.farm_count(rt)
    local max_farms = h.age() >= 1 and 12 or 8
    if current_farms >= max_farms then return false end
    local idle = h.idle_vils()
    if #idle == 0 and current_farms > 0 then return false end
    if not h.can_afford(0, 60, 0, 0) then return false end
    return h.build_farm()
end

local function assign_idle_by_count()
    local idle = h.idle_vils()
    if #idle == 0 then return false end
    local pop = h.pop()
    local n = pop.vils

    if n <= 6 then
        return assign_to_food(idle)
    elseif n <= 9 then
        return assign_to_wood(idle)
    elseif n <= 17 then
        return assign_to_food(idle)
    elseif n <= 21 then
        return assign_to_wood(idle)
    else
        local r = h.resources()
        if r.food < 200 then
            return assign_to_food(idle)
        elseif r.wood < 100 then
            return assign_to_wood(idle)
        else
            return assign_to_food(idle)
        end
    end
end

local function build_lumber_camp()
    if sync_building("lc", "LUMBER") ~= "none" then return false end
    local pop = h.pop()
    if pop.vils < 7 then return false end
    if not h.can_afford(0, 100, 0, 0) then return false end

    local tc = h.tc_pos()
    local cluster = h.find_tree_cluster(rt, tc)
    local built = cluster
        and h.build_at("LUMBER_CAMP_DARK_AGE", cluster)
        or h.build_near_tc("LUMBER_CAMP_DARK_AGE")
    if built then
        state.lc = "ordered"
        state.lc_ordered_at = state.tick
    end
    return built
end

local function build_mill()
    if sync_building("mill", "MILL") ~= "none" then return false end
    if sync_building("lc", "LUMBER") ~= "done" then return false end
    local pop = h.pop()
    if pop.vils < 10 then return false end
    if not h.can_afford(0, 100, 0, 0) then return false end

    local tc = h.tc_pos()
    local berries = h.find_berry_pos(rt, tc)
    local built = berries
        and h.build_at("MILL_DARK_AGE", berries)
        or h.build_near_tc("MILL_DARK_AGE")
    if built then
        state.mill = "ordered"
        state.mill_ordered_at = state.tick
    end
    return built
end

local function build_mining_camp()
    if sync_building("mc", "MINING") ~= "none" then return false end
    local pop = h.pop()
    if pop.vils < 20 then return false end
    if not h.can_afford(0, 100, 0, 0) then return false end

    local tc = h.tc_pos()
    local gold = h.find_gold_pos(rt, tc)
    local built = gold
        and h.build_at("MINING_CAMP_DARK_AGE", gold)
        or h.build_near_tc("MINING_CAMP_DARK_AGE")
    if built then
        state.mc = "ordered"
        state.mc_ordered_at = state.tick
    end
    return built
end

local function research_loom()
    if state.loom_done then return false end
    local pop = h.pop()
    if pop.vils < 20 then return false end
    if not h.can_afford(0, 0, 50, 0) then return false end
    if h.is_researched(TECH_LOOM) then
        state.loom_done = true
        return false
    end
    local ok = h.research(TECH_LOOM, "Loom")
    if ok then state.loom_done = true end
    return ok
end

local function click_feudal()
    if state.feudal_clicked then return false end
    if not state.loom_done then return false end
    if not h.can_afford(500, 0, 0, 0) then return false end
    if not h.can_research(TECH_FEUDAL) then return false end

    local dark_buildings = #h.buildings("LUMBER") + #h.buildings("MILL")
        + #h.buildings("MINING") + #h.buildings("BARRACKS")
    if dark_buildings < 2 then return false end

    local ok = h.research(TECH_FEUDAL, "Feudal Age")
    if ok then state.feudal_clicked = true end
    return ok
end

local function feudal_upgrades()
    if h.age() < 1 then return false end
    if not h.is_researched(TECH_DOUBLE_BIT_AXE) and h.can_research(TECH_DOUBLE_BIT_AXE) then
        return h.research(TECH_DOUBLE_BIT_AXE, "Double-Bit Axe")
    end
    if not h.is_researched(TECH_HORSE_COLLAR) and h.can_research(TECH_HORSE_COLLAR) then
        return h.research(TECH_HORSE_COLLAR, "Horse Collar")
    end
    return false
end

local function build_barracks()
    if sync_building("barracks", "BARRACKS") ~= "none" then return false end
    local pop = h.pop()
    if pop.vils < 18 then return false end
    if not h.can_afford(0, 175, 0, 0) then return false end
    local ok = h.build_near_tc("BARRACKS_DARK_AGE")
    if ok then
        state.barracks = "ordered"
        state.barracks_ordered_at = state.tick
    end
    return ok
end

local function build_archery_range()
    if sync_building("range", "ARCHERY") ~= "none" then return false end
    if h.age() < 1 then return false end
    if sync_building("barracks", "BARRACKS") ~= "done" then return false end
    if not h.can_afford(0, 175, 0, 0) then return false end
    local ok = h.build_near_tc("ARCHERY_RANGE_FEUDAL_AGE")
    if ok then
        state.range = "ordered"
        state.range_ordered_at = state.tick
    end
    return ok
end

local function train_military()
    if h.age() < 1 then return false end
    if #h.buildings("ARCHERY") == 0 then return false end
    if not h.can_afford(25, 45, 0, 0) and not h.can_afford(25, 35, 0, 0) then return false end
    local r = h.resources()
    local result
    if r.gold >= 45 then
        result = h.get("train_archer", function()
            local typeId = UnitObjectType["ARCHER_FEUDAL_AGE"] or UnitObjectType["ARCHER"]
            if not typeId then return false end
            return TrainUnit(typeId)
        end, false)
        if result then event_log.add("train archer"); return true end
    end
    result = h.get("train_skirm", function()
        local typeId = UnitObjectType["SKIRMISHER_FEUDAL_AGE"] or UnitObjectType["SKIRMISHER"]
        if not typeId then return false end
        return TrainUnit(typeId)
    end, false)
    if result then event_log.add("train skirmisher"); return true end
    return false
end

local function herd_livestock()
    if not rt then return false end
    local tc = h.tc_pos()
    if not tc then return false end
    return h.get("herd", function()
        local owned = rt:GetOwnedLivestock()
        if not owned then return false end
        local far = {}
        for _, o in ipairs(owned) do
            if h.dist(o:GetPosition(), tc) > 8 then
                table.insert(far, o)
            end
        end
        if #far > 0 then
            h.move(far, tc)
            return true
        end
        return false
    end, false)
end

-- ── Main Tick ──

function bo.update(resource_tracker)
    rt = resource_tracker
    state.tick = state.tick + 1

    local ok, err = pcall(function()
        ensure_scouting()
        if ensure_houses() then return end
        if ensure_training() then return end

        if not state.food_forced then
            if force_initial_food() then return end
        end

        if build_lumber_camp() then return end
        if build_mill() then return end
        if ensure_farms() then return end
        if assign_idle_by_count() then return end
        if build_barracks() then return end
        if build_mining_camp() then return end

        if research_loom() then return end
        if click_feudal() then return end
        if feudal_upgrades() then return end
        if build_archery_range() then return end
        if train_military() then return end

        if state.tick % 5 == 0 then herd_livestock() end
    end)
    if not ok then Log("[BO] ERR tick " .. state.tick .. ": " .. tostring(err)) end
end

return bo
