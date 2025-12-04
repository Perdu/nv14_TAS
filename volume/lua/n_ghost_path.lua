-- AI-generated
-- ==============================
-- Ghost path display for libTAS
-- Full line always, dots up to current frame
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
-- Draw full path always, dots only up to current frame
-- ------------------------------
function onPaint()
    local f = movie.currentFrame()

    -- ---- Full line always ----
    for i = 1, #sortedFrames - 1 do
        local a = ghostData[sortedFrames[i]]
        local b = ghostData[sortedFrames[i+1]]
        gui.line(a.x, a.y, b.x, b.y, 0xffff00ff)
    end

    -- ---- Dots only up to CURRENT frame ----
    for i = 1, #sortedFrames do
        local frame = sortedFrames[i]
        if frame > f then
            break   -- stop once we pass current frame
        end

        local p = ghostData[frame]

        -- round to nearest pixel (required for gui.pixel)
        local x = math.floor(p.x + 0.5)
        local y = math.floor(p.y + 0.5)

        gui.ellipse(p.x, p.y, 1, 1, 1, 0xffffff00) -- yellow dot
    end

    -- Optional: display ghost coords at current frame
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
