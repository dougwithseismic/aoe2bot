local overlay = {}
local event_log = require("event_log")

local PANEL_PADDING = 10
local LINE_HEIGHT = 16
local FONT_SIZE = 14

local COL_BG = Color(0, 0, 0, 180)
local COL_HEADER = Color(255, 200, 50, 255)
local COL_TEXT = Color(220, 220, 220, 255)
local COL_FOOD = Color(200, 50, 50, 255)
local COL_WOOD = Color(100, 200, 50, 255)
local COL_GOLD = Color(255, 215, 0, 255)
local COL_STONE = Color(150, 150, 150, 255)
local COL_LOG_BG = Color(0, 0, 0, 160)
local COL_LOG_TIME = Color(120, 180, 255, 255)
local COL_LOG_TEXT = Color(200, 200, 200, 255)
local COL_ERROR = Color(255, 80, 80, 255)

local AGE_NAMES = { [0] = "Dark", [1] = "Feudal", [2] = "Castle", [3] = "Imperial" }

function overlay.render()
    local screen = GetScreenSize()
    if not screen then return end
    overlay.render_state_panel(screen)
    overlay.render_event_log(screen)
    overlay.render_errors(screen)
end

function overlay.render_state_panel(screen)
    local x, y = PANEL_PADDING, PANEL_PADDING + 40
    local w, h = 220, PANEL_PADDING * 2 + LINE_HEIGHT * 8

    RenderRectFilled(Vector2(x, y), Vector2(x + w, y + h), COL_BG, 4, 15)

    local cy = y + PANEL_PADDING
    local tx = x + PANEL_PADDING

    RenderText("GAME STATE", Vector2(tx, cy), FONT_SIZE, COL_HEADER, false, true)
    cy = cy + LINE_HEIGHT + 4

    local time = GetGameTime() or 0
    RenderText(string.format("Time: %02d:%02d", math.floor(time/60), math.floor(time%60)), Vector2(tx, cy), FONT_SIZE, COL_TEXT, false, false)
    cy = cy + LINE_HEIGHT

    local age = 0
    if Fact.CURRENT_AGE then age = GetFact(Fact.CURRENT_AGE) or 0 end
    RenderText("Age: " .. (AGE_NAMES[age] or tostring(age)), Vector2(tx, cy), FONT_SIZE, COL_TEXT, false, false)
    cy = cy + LINE_HEIGHT

    local pop = GetFact(Fact.POPULATION) or 0
    local housing = pop
    if Fact.POPULATION_HEADROOM then housing = pop + (GetFact(Fact.POPULATION_HEADROOM) or 0) end
    RenderText(string.format("Pop: %d / %d", pop, housing), Vector2(tx, cy), FONT_SIZE, COL_TEXT, false, false)
    cy = cy + LINE_HEIGHT + 4

    local food = GetFact(Fact.FOOD_AMOUNT) or 0
    local wood = GetFact(Fact.WOOD_AMOUNT) or 0
    local gold = GetFact(Fact.GOLD_AMOUNT) or 0
    local stone = GetFact(Fact.STONE_AMOUNT) or 0

    RenderText(string.format("Food:  %d", math.floor(food)), Vector2(tx, cy), FONT_SIZE, COL_FOOD, false, false)
    cy = cy + LINE_HEIGHT
    RenderText(string.format("Wood:  %d", math.floor(wood)), Vector2(tx, cy), FONT_SIZE, COL_WOOD, false, false)
    cy = cy + LINE_HEIGHT
    RenderText(string.format("Gold:  %d", math.floor(gold)), Vector2(tx, cy), FONT_SIZE, COL_GOLD, false, false)
    cy = cy + LINE_HEIGHT
    RenderText(string.format("Stone: %d", math.floor(stone)), Vector2(tx, cy), FONT_SIZE, COL_STONE, false, false)
end

function overlay.render_event_log(screen)
    local entries = event_log.get_entries()
    if #entries == 0 then return end

    local maxShow = 12
    local count = math.min(#entries, maxShow)
    local w = 420
    local h = PANEL_PADDING * 2 + LINE_HEIGHT * count + LINE_HEIGHT + 4
    local x = screen.x - w - PANEL_PADDING
    local y = PANEL_PADDING + 40

    RenderRectFilled(Vector2(x, y), Vector2(x + w, y + h), COL_LOG_BG, 4, 15)

    local cy = y + PANEL_PADDING
    local tx = x + PANEL_PADDING

    RenderText("EVENT LOG", Vector2(tx, cy), FONT_SIZE, COL_HEADER, false, true)
    cy = cy + LINE_HEIGHT + 4

    for i = 1, count do
        local entry = entries[i]
        RenderText(entry.time, Vector2(tx, cy), FONT_SIZE, COL_LOG_TIME, false, false)
        RenderText(entry.text, Vector2(tx + 50, cy), FONT_SIZE, COL_LOG_TEXT, false, false)
        cy = cy + LINE_HEIGHT
    end
end

function overlay.render_errors(screen)
    local helpers_ok, helpers = pcall(require, "helpers")
    if not helpers_ok then return end
    local errs = helpers.get_errors()
    if #errs == 0 then return end

    local maxShow = 6
    local count = math.min(#errs, maxShow)
    local w = 600
    local h = PANEL_PADDING * 2 + LINE_HEIGHT * count + LINE_HEIGHT + 4
    local x = (screen.x - w) / 2
    local y = screen.y - h - PANEL_PADDING - 40

    RenderRectFilled(Vector2(x, y), Vector2(x + w, y + h), Color(40, 0, 0, 200), 4, 15)

    local cy = y + PANEL_PADDING
    RenderText("ERRORS (" .. #errs .. ")", Vector2(x + PANEL_PADDING, cy), FONT_SIZE, COL_ERROR, false, true)
    cy = cy + LINE_HEIGHT + 4

    for i = 1, count do
        RenderText(errs[i], Vector2(x + PANEL_PADDING, cy), FONT_SIZE, COL_ERROR, false, false)
        cy = cy + LINE_HEIGHT
    end
end

return overlay
