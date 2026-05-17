-- 22-Pop Scout Rush Build Order
-- Priority-based: critical actions always run first, then build order steps.

local query = require("helpers.query")
local spatial = require("helpers.spatial")
local command = require("helpers.command")
local event_log = require("event_log")

local bo = {}

local TECH_LOOM = 22
local TECH_FEUDAL = 101
local TECH_DOUBLE_BIT_AXE = 202
local TECH_HORSE_COLLAR = 14

local state = {
    tick = 0,
    scouting = false,
    wood_target = nil,
    built = {},
    house_cd = 0,
    food_forced = false,
    feudal_clicked = false,
    loom_done = false,
}

local rt = nil

function bo.init(resource_tracker)
    rt = resource_tracker
    state = {
        tick = 0,
        scouting = false,
        wood_target = nil,
        built = {},
        house_cd = 0,
        food_forced = false,
        feudal_clicked = false,
        loom_done = false,
    }
end

-- ── Priority Actions (always checked) ──

local function ensure_houses()
    if state.house_cd > 0 then return false end
    local pop = query.pop()
    if pop.headroom > 3 then return false end
    if not query.can_afford(0, 25, 0, 0) then return false end
    local ok = command.build_near_tc("HOUSE_DARK_AGE", 2, -4, 4)
    if ok then state.house_cd = 10 end
    return ok
end

local function ensure_training()
    local pop = query.pop()
    if pop.headroom <= 0 then return false end
    if not query.can_afford(50, 0, 0, 0) then return false end
    local tcs = query.tcs()
    if #tcs == 0 then return false end
    local ok, idle = pcall(function() return tcs[1]:IsIdle() end)
    if not ok or not idle then return false end
    return command.train_vil()
end

local function ensure_scouting()
    if state.scouting then return false end
    local scout = query.scout()
    if not scout then return false end
    state.scouting = true
    return command.auto_scout(scout)
end

-- ── Resource Helpers ──

local function refresh_wood_target()
    local tc = query.tc_pos()
    if not tc or not rt then return end
    if state.wood_target then
        local ok, alive = pcall(function() return state.wood_target:IsAlive() end)
        if ok and alive then return end
    end
    state.wood_target = spatial.find_safe_trees(rt, tc)
end

local function assign_to_food(vils)
    local tc = query.tc_pos()
    if not tc then return false end
    local food = spatial.find_food(rt, tc)
    if not food then return false end
    return command.gather(vils, food)
end

local function assign_to_wood(vils)
    refresh_wood_target()
    if not state.wood_target then return false end
    return command.gather(vils, state.wood_target)
end

local function assign_to_gold(vils)
    local tc = query.tc_pos()
    if not tc then return false end
    local gold = spatial.find_gold(rt, tc)
    if not gold then return false end
    return command.gather(vils, gold)
end

-- ── Build Order Steps ──

local function force_initial_food()
    if state.food_forced then return false end
    local vils = query.vils()
    if #vils == 0 then return false end
    local ok = assign_to_food(vils)
    if ok then
        state.food_forced = true
        event_log.add("all vils → food (" .. #vils .. " vils)")
    end
    return ok
end

local function assign_idle_by_count()
    local idle = query.idle_vils()
    if #idle == 0 then return false end
    local pop = query.pop()
    local n = pop.vils

    -- 22-pop scout rush distribution:
    -- Vils 1-6: food (sheep)
    -- Vils 7-9: wood (lumber camp)
    -- Vils 10-13: food (boar/berries)
    -- Vils 14-17: food (berries/sheep)
    -- Vils 18-21: wood
    -- After Feudal click: maintain ratio
    if n <= 6 then
        return assign_to_food(idle)
    elseif n <= 9 then
        return assign_to_wood(idle)
    elseif n <= 17 then
        return assign_to_food(idle)
    elseif n <= 21 then
        return assign_to_wood(idle)
    else
        local r = query.resources()
        if r.food < 200 then
            return assign_to_food(idle)
        else
            return assign_to_wood(idle)
        end
    end
end

local function build_lumber_camp()
    if state.built.lc then return false end
    local pop = query.pop()
    if pop.vils < 7 then return false end
    if not query.can_afford(0, 100, 0, 0) then return false end

    refresh_wood_target()
    if not state.wood_target then return false end

    local tc = query.tc_pos()
    if not tc then return false end

    local ok, wpos = pcall(function() return state.wood_target:GetPosition() end)
    if not ok then return false end

    local dx, dy = tc.x - wpos.x, tc.y - wpos.y
    local d = math.max(math.sqrt(dx * dx + dy * dy), 0.1)
    local spot = spatial.find_placement(
        math.floor(wpos.x + dx / d * 3),
        math.floor(wpos.y + dy / d * 3),
        2
    )
    if not spot then return false end

    local built = command.build("LUMBER_CAMP_DARK_AGE", spot)
    if built then state.built.lc = true end
    return built
end

local function build_mill()
    if state.built.mill then return false end
    if not state.built.lc then return false end
    local pop = query.pop()
    if pop.vils < 10 then return false end
    if not query.can_afford(0, 100, 0, 0) then return false end

    local tc = query.tc_pos()
    if not tc or not rt then return false end

    local ok, result = pcall(function()
        local forage = rt:GetForage()
        if forage and #forage > 0 then
            local best, d = spatial.nearest(forage, tc)
            if best and d < 20 then
                local fp = best:GetPosition()
                local dx, dy = tc.x - fp.x, tc.y - fp.y
                local dd = math.max(math.sqrt(dx * dx + dy * dy), 0.1)
                return Vector3(fp.x + dx / dd * 2, fp.y + dy / dd * 2, 0)
            end
        end
        return Vector3(tc.x + 5, tc.y, 0)
    end)
    if not ok then return false end

    local spot = spatial.find_placement(math.floor(result.x), math.floor(result.y), 2)
    if not spot then return false end

    local built = command.build("MILL_DARK_AGE", spot)
    if built then state.built.mill = true end
    return built
end

local function build_mining_camp()
    if state.built.mc then return false end
    local pop = query.pop()
    if pop.vils < 20 then return false end
    if not query.can_afford(0, 100, 0, 0) then return false end

    local tc = query.tc_pos()
    if not tc then return false end

    local gold, d = spatial.find_gold(rt, tc)
    if not gold or d > 30 then return false end

    local ok, gp = pcall(function() return gold:GetPosition() end)
    if not ok then return false end

    local dx, dy = tc.x - gp.x, tc.y - gp.y
    local dd = math.max(math.sqrt(dx * dx + dy * dy), 0.1)
    local spot = spatial.find_placement(
        math.floor(gp.x + dx / dd * 3),
        math.floor(gp.y + dy / dd * 3),
        2
    )
    if not spot then return false end

    local built = command.build("MINING_CAMP_DARK_AGE", spot)
    if built then state.built.mc = true end
    return built
end

local function research_loom()
    if state.loom_done then return false end
    local pop = query.pop()
    if pop.vils < 20 then return false end
    if not query.can_afford(0, 0, 50, 0) then return false end
    if query.is_researched(TECH_LOOM) then
        state.loom_done = true
        return false
    end
    local ok = command.research(TECH_LOOM, "Loom")
    if ok then state.loom_done = true end
    return ok
end

local function click_feudal()
    if state.feudal_clicked then return false end
    if not state.loom_done then return false end
    if not query.can_afford(500, 0, 0, 0) then return false end
    if not query.can_research(TECH_FEUDAL) then return false end

    local dark_buildings = #query.buildings("LUMBER") + #query.buildings("MILL")
        + #query.buildings("MINING") + #query.buildings("BARRACKS")
    if dark_buildings < 2 then return false end

    local ok = command.research(TECH_FEUDAL, "Feudal Age")
    if ok then state.feudal_clicked = true end
    return ok
end

local function feudal_upgrades()
    if query.age() < 1 then return false end
    if not query.is_researched(TECH_DOUBLE_BIT_AXE) and query.can_research(TECH_DOUBLE_BIT_AXE) then
        return command.research(TECH_DOUBLE_BIT_AXE, "Double-Bit Axe")
    end
    if not query.is_researched(TECH_HORSE_COLLAR) and query.can_research(TECH_HORSE_COLLAR) then
        return command.research(TECH_HORSE_COLLAR, "Horse Collar")
    end
    return false
end

local function herd_livestock()
    if not rt then return false end
    local tc = query.tc_pos()
    if not tc then return false end

    local ok, result = pcall(function()
        local owned = rt:GetOwnedLivestock()
        if not owned then return false end
        local far = {}
        for _, o in ipairs(owned) do
            if spatial.dist(o:GetPosition(), tc) > 8 then
                table.insert(far, o)
            end
        end
        if #far > 0 then
            UnitsMove(far, tc)
            return true
        end
        return false
    end)
    return ok and result or false
end

-- ── Main Tick ──

function bo.update(resource_tracker)
    rt = resource_tracker
    state.tick = state.tick + 1
    if state.house_cd > 0 then state.house_cd = state.house_cd - 1 end

    -- Priority 1: Critical (every tick)
    ensure_scouting()
    if ensure_houses() then return end
    if ensure_training() then return end

    -- Priority 2: Initial setup
    if not state.food_forced then
        if force_initial_food() then return end
    end

    -- Priority 3: Eco buildings (when conditions met)
    if build_lumber_camp() then return end
    if build_mill() then return end
    if build_mining_camp() then return end

    -- Priority 4: Assign idle vils
    if assign_idle_by_count() then return end

    -- Priority 5: Age progression
    if research_loom() then return end
    if click_feudal() then return end
    if feudal_upgrades() then return end

    -- Priority 6: Maintenance
    if state.tick % 5 == 0 then herd_livestock() end
end

return bo
