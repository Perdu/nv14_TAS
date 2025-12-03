-- AI-generated
-- ==============================
-- Ghost path display for libTAS
-- Reads CSV and draws full ghost path
-- ==============================

local ghostData = {}      -- frame → {x, y}
local level = nil
local ghostFilePath = nil
local sortedFrames = {}   -- ordered list of frame numbers

-- ------------------------------
-- Reads CSV file into ghostData
-- ------------------------------
local function loadGhost()
    local file = io.open(ghostFilePath, "r")
    if not file then
        print("ERROR: Could not open ghost CSV file!")
        return
    end

    for line in file:lines() do
        local frame, x, y = line:match("(%d+),([^,]+),([^,]+)")
        if frame and x and y then
            frame = tonumber(frame)
            ghostData[frame] = { x = tonumber(x), y = tonumber(y) }
            table.insert(sortedFrames, frame)
        end
    end

    file:close()

    table.sort(sortedFrames)

    print("Ghost loaded: " .. tostring(#sortedFrames) .. " frames")
end

-- ------------------------------
-- Draw full ghost path (no limits)
-- ------------------------------
function onPaint()
    -- Draw ALL line segments, ignoring current frame
    for i = 1, #sortedFrames - 1 do
        local a = ghostData[sortedFrames[i]]
        local b = ghostData[sortedFrames[i+1]]

        gui.line(a.x, a.y, b.x, b.y, 0xffff00ff) -- yellow-magenta line
    end

    -- Optional: display exact ghost coords at current frame
    local f = movie.currentFrame()
    local ghost = ghostData[f]
    if ghost then
        gui.text(610, 580, string.format("%f ; %f", ghost.x, ghost.y))
    end
end

-- ------------------------------
-- Startup: detect level and load CSV
-- ------------------------------
function onStartup()
    level = movie.getMovieFileName():match("/(%d+-%d+).*%.ltm$")
    ghostFilePath = "/home/ghosts/" .. level .. ".csv"
    loadGhost()
end
