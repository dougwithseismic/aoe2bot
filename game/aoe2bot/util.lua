-- AoE2Bot utility functions
-- Shared helpers used by commands.lua, queries.lua, and main.lua

local util = {}

--- Safely call GetFact, returning 0 on failure
function util.safeGetFact(fact, param)
    if fact == nil then return 0 end
    local ok, val
    if param ~= nil then
        ok, val = pcall(GetFact, fact, param)
    else
        ok, val = pcall(GetFact, fact)
    end
    return ok and val or 0
end

--- Resolve a building name to its UnitObjectType enum value.
--- Handles age-suffixed names (e.g. HOUSE_DARK_AGE) and TC foundation logic.
--- Returns typeId, resolvedName or nil, originalName
function util.resolveBuildingType(name)
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

    local age = util.safeGetFact(Fact.CURRENT_AGE)
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

--- Resolve a list of unit IDs to live game objects
function util.resolveUnits(unitIds)
    local units = {}
    for _, id in ipairs(unitIds) do
        local ok, obj = pcall(GetObjectById, id)
        if ok and obj and obj:IsAlive() then table.insert(units, obj) end
    end
    return units
end

--- Look up values in a global enum table (UnitObjectType, Technology, etc.)
function util.enumLookup(msg)
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

return util
