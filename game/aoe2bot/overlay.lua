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

local AGE_NAMES = { [0] = "Dark", [1] = "Feudal", [2] = "Castle", [3] = "Imperial" }

local STATE_X = PANEL_PADDING
local STATE_Y = PANEL_PADDING + 40
local STATE_W = 220
local STATE_H = PANEL_PADDING * 2 + LINE_HEIGHT * 8
local STATE_TX = STATE_X + PANEL_PADDING
local STATE_TL = Vector2(STATE_X, STATE_Y)
local STATE_BR = Vector2(STATE_X + STATE_W, STATE_Y + STATE_H)

local pos = Vector2(0, 0)

local function setPos(x, y)
    pos.x = x
    pos.y = y
    return pos
end

function overlay.render()
    local screen = GetScreenSize()
    if not screen then return end

    overlay.render_state_panel(screen)
    overlay.render_event_log(screen)
end

function overlay.render_state_panel(screen)
    RenderRectFilled(STATE_TL, STATE_BR, COL_BG, 4, 15)

    local cy = STATE_Y + PANEL_PADDING

    RenderText("GAME STATE", setPos(STATE_TX, cy), FONT_SIZE, COL_HEADER, false, true)
    cy = cy + LINE_HEIGHT + 4

    local time = GetGameTime() or 0
    local mins = math.floor(time / 60)
    local secs = math.floor(time % 60)
    RenderText(string.format("Time: %02d:%02d", mins, secs), setPos(STATE_TX, cy), FONT_SIZE, COL_TEXT, false, false)
    cy = cy + LINE_HEIGHT

    local age = GetFact(Fact.CURRENT_AGE)
    if age == nil then age = 0 end
    local ageName = AGE_NAMES[age] or ("Age " .. tostring(age))
    RenderText("Age: " .. ageName, setPos(STATE_TX, cy), FONT_SIZE, COL_TEXT, false, false)
    cy = cy + LINE_HEIGHT

    local pop = GetFact(Fact.POPULATION) or 0
    local popCap = GetFact(Fact.POPULATION_CAP) or 0
    RenderText(string.format("Pop: %d / %d", pop, popCap), setPos(STATE_TX, cy), FONT_SIZE, COL_TEXT, false, false)
    cy = cy + LINE_HEIGHT + 4

    local food = GetFact(Fact.FOOD_AMOUNT) or 0
    local wood = GetFact(Fact.WOOD_AMOUNT) or 0
    local gold = GetFact(Fact.GOLD_AMOUNT) or 0
    local stone = GetFact(Fact.STONE_AMOUNT) or 0

    RenderText(string.format("Food:  %d", math.floor(food)), setPos(STATE_TX, cy), FONT_SIZE, COL_FOOD, false, false)
    cy = cy + LINE_HEIGHT
    RenderText(string.format("Wood:  %d", math.floor(wood)), setPos(STATE_TX, cy), FONT_SIZE, COL_WOOD, false, false)
    cy = cy + LINE_HEIGHT
    RenderText(string.format("Gold:  %d", math.floor(gold)), setPos(STATE_TX, cy), FONT_SIZE, COL_GOLD, false, false)
    cy = cy + LINE_HEIGHT
    RenderText(string.format("Stone: %d", math.floor(stone)), setPos(STATE_TX, cy), FONT_SIZE, COL_STONE, false, false)
end

local LOG_MAX_SHOW = 12
local LOG_W = 420
local LOG_Y = PANEL_PADDING + 40

function overlay.render_event_log(screen)
    local entries = event_log.get_entries()
    if #entries == 0 then return end

    local count = math.min(#entries, LOG_MAX_SHOW)
    local h = PANEL_PADDING * 2 + LINE_HEIGHT * count + LINE_HEIGHT + 4
    local x = screen.x - LOG_W - PANEL_PADDING
    local tx = x + PANEL_PADDING

    RenderRectFilled(setPos(x, LOG_Y), Vector2(x + LOG_W, LOG_Y + h), COL_LOG_BG, 4, 15)

    local cy = LOG_Y + PANEL_PADDING
    RenderText("EVENT LOG", setPos(tx, cy), FONT_SIZE, COL_HEADER, false, true)
    cy = cy + LINE_HEIGHT + 4

    for i = 1, count do
        local entry = entries[i]
        RenderText(entry.time, setPos(tx, cy), FONT_SIZE, COL_LOG_TIME, false, false)
        RenderText(entry.text, setPos(tx + 50, cy), FONT_SIZE, COL_LOG_TEXT, false, false)
        cy = cy + LINE_HEIGHT
    end
end

return overlay
