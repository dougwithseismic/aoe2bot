local event_log = {}

local MAX_ENTRIES = 20
local entries = {}

function event_log.add(message)
    local time = GetGameTime() or 0
    local mins = math.floor(time / 60)
    local secs = math.floor(time % 60)
    local timestamp = string.format("%02d:%02d", mins, secs)

    table.insert(entries, 1, { time = timestamp, text = message })

    if #entries > MAX_ENTRIES then
        table.remove(entries, #entries)
    end

    Log("[AoE2Bot] " .. timestamp .. " | " .. message)
end

function event_log.get_entries()
    return entries
end

function event_log.clear()
    entries = {}
end

return event_log
