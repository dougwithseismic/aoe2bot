local spatial = {}

function spatial.dist(a, b)
    local dx, dy = a.x - b.x, a.y - b.y
    return math.sqrt(dx * dx + dy * dy)
end

function spatial.nearest(objects, pos)
    if not objects or #objects == 0 then return nil, math.huge end
    local best, bestDist = nil, math.huge
    for _, obj in ipairs(objects) do
        local ok, opos = pcall(function() return obj:GetPosition() end)
        if ok and opos then
            local d = spatial.dist(opos, pos)
            if d < bestDist then best = obj; bestDist = d end
        end
    end
    return best, bestDist
end

function spatial.nearest_within(objects, pos, radius)
    local best, d = spatial.nearest(objects, pos)
    if best and d <= radius then return best, d end
    return nil, math.huge
end

function spatial.filter_within(objects, pos, radius)
    local out = {}
    for _, obj in ipairs(objects or {}) do
        local ok, opos = pcall(function() return obj:GetPosition() end)
        if ok and opos and spatial.dist(opos, pos) <= radius then
            table.insert(out, obj)
        end
    end
    return out
end

-- Check if a building footprint is clear of obstacles.
-- Ignores villagers (904), scouts (961), livestock (958) on tiles.
function spatial.is_footprint_clear(cx, cy, size)
    local half = math.floor(size / 2)
    for dx = -half, half - 1 do
        for dy = -half, half - 1 do
            local tile = GetMapTile(math.floor(cx) + dx, math.floor(cy) + dy)
            if not tile then return false end

            local ok, clear = pcall(function()
                if not tile:IsBuildable() or not tile:IsWalkable() then return false end
                if tile:GetObjectCount() > 0 then
                    for _, obj in ipairs(tile:GetObjects()) do
                        local cls = obj:GetClass()
                        if cls ~= 904 and cls ~= 961 and cls ~= 958 then
                            return false
                        end
                    end
                end
                return true
            end)
            if not ok or not clear then return false end
        end
    end
    return true
end

-- Spiral outward from a center point to find a valid building spot.
function spatial.find_placement(cx, cy, size, max_radius)
    max_radius = max_radius or 10
    for r = 0, max_radius, 2 do
        for _, off in ipairs({{r,0},{-r,0},{0,r},{0,-r},{r,r},{-r,r},{r,-r},{-r,-r}}) do
            local x, y = cx + off[1], cy + off[2]
            if spatial.is_footprint_clear(x, y, size) then
                return Vector3(x, y, 0)
            end
        end
    end
    return nil
end

-- Find trees on the "safe side" (away from map center, toward your corner).
function spatial.find_safe_trees(rt, tc_pos)
    if not rt or not tc_pos then return nil end
    local ok, result = pcall(function()
        local trees = rt:GetTrees()
        local near = {}
        for _, t in ipairs(trees) do
            if spatial.dist(t:GetPosition(), tc_pos) < 20 then
                table.insert(near, t)
            end
        end
        if #near == 0 then return nil end

        local mapW, mapH = GetMapWidth(), GetMapHeight()
        local safeX, safeY = tc_pos.x - mapW / 2, tc_pos.y - mapH / 2
        table.sort(near, function(a, b)
            local pa, pb = a:GetPosition(), b:GetPosition()
            local scoreA = (pa.x - tc_pos.x) * safeX + (pa.y - tc_pos.y) * safeY
            local scoreB = (pb.x - tc_pos.x) * safeX + (pb.y - tc_pos.y) * safeY
            return scoreA > scoreB
        end)
        return near[1]
    end)
    return ok and result or nil
end

function spatial.find_food(rt, tc_pos)
    if not rt or not tc_pos then return nil end
    local ok, result = pcall(function()
        local owned = rt:GetOwnedLivestock()
        if owned then
            local near = spatial.filter_within(owned, tc_pos, 15)
            if #near > 0 then return spatial.nearest(near, tc_pos) end
        end
        local forage = rt:GetForage()
        if forage then
            local best, d = spatial.nearest(forage, tc_pos)
            if best and d < 20 then return best end
        end
        return nil
    end)
    return ok and result or nil
end

function spatial.find_gold(rt, tc_pos)
    if not rt or not tc_pos then return nil end
    local ok, result = pcall(function() return rt:GetGold() end)
    if not ok or not result then return nil end
    return spatial.nearest(result, tc_pos)
end

function spatial.find_stone(rt, tc_pos)
    if not rt or not tc_pos then return nil end
    local ok, result = pcall(function() return rt:GetStone() end)
    if not ok or not result then return nil end
    return spatial.nearest(result, tc_pos)
end

return spatial
