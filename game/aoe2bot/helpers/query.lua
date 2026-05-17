local query = {}

-- Each function has ONE pcall at the boundary.
-- On failure: tables return {}, numbers return 0, objects return nil.

function query.player()
    return GetAssignedPlayer()
end

function query.vils()
    local ok, result = pcall(function()
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
    end)
    return ok and result or {}
end

function query.idle_vils()
    local ok, result = pcall(function()
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
    end)
    return ok and result or {}
end

function query.scout()
    local ok, result = pcall(function()
        local p = GetAssignedPlayer()
        for _, u in ipairs(p:GetObjectsByClass(961)) do
            if u:IsAlive() then return u end
        end
        return nil
    end)
    return ok and result or nil
end

function query.tcs()
    local ok, result = pcall(function()
        return GetAssignedPlayer():GetTownCenters()
    end)
    return ok and result or {}
end

function query.tc_pos()
    local tcs = query.tcs()
    if #tcs > 0 then
        local ok, pos = pcall(function() return tcs[1]:GetPosition() end)
        if ok then return pos end
    end
    return nil
end

function query.pop()
    local ok, result = pcall(function()
        local current = GetFact(Fact.POPULATION)
        local headroom = GetFact(Fact.POPULATION_HEADROOM)
        return {
            current = current,
            headroom = headroom,
            housing = current + headroom,
            vils = GetFact(Fact.VILLAGER_COUNT),
        }
    end)
    return ok and result or { current = 0, headroom = 0, housing = 0, vils = 0 }
end

function query.resources()
    local ok, result = pcall(function()
        return {
            food = GetFact(Fact.FOOD_AMOUNT),
            wood = GetFact(Fact.WOOD_AMOUNT),
            gold = GetFact(Fact.GOLD_AMOUNT),
            stone = GetFact(Fact.STONE_AMOUNT),
        }
    end)
    return ok and result or { food = 0, wood = 0, gold = 0, stone = 0 }
end

function query.age()
    local ok, result = pcall(function() return GetFact(Fact.CURRENT_AGE) end)
    return ok and result or 0
end

function query.game_time()
    local ok, result = pcall(function() return GetGameTime() end)
    return ok and result or 0
end

function query.can_afford(food, wood, gold, stone)
    local r = query.resources()
    return r.food >= (food or 0) and r.wood >= (wood or 0)
        and r.gold >= (gold or 0) and r.stone >= (stone or 0)
end

function query.is_researched(tech_id)
    local ok, result = pcall(function() return IsTechnologyResearched(tech_id) end)
    return ok and result or false
end

function query.can_research(tech_id)
    local ok, result = pcall(function() return CanResearch(tech_id) end)
    return ok and result or false
end

function query.buildings(name_pattern)
    local ok, result = pcall(function()
        local p = GetAssignedPlayer()
        local all = p:GetPlayerObjects()
        local out = {}
        for _, o in ipairs(all) do
            if o:IsAlive() then
                local name = string.upper(o:GetName() or "")
                if string.find(name, name_pattern) then
                    table.insert(out, o)
                end
            end
        end
        return out
    end)
    return ok and result or {}
end

return query
