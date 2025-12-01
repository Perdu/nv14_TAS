-- AI-generated
-- ==============================
-- Ghost display for libTAS
-- Reads CSV and draws 10px circle
-- ==============================

local ghostData = {}      -- frame → {x, y}
local level = nil
local ghostFilePath = nil

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
            ghostData[tonumber(frame)] = { x = tonumber(x), y = tonumber(y) }
        end
    end

    file:close()
    print("Ghost loaded: " .. tostring(#ghostData) .. " frames")
end

function onPaint()
   local f = movie.currentFrame()
   local ghost = ghostData[f]
   if ghost then
      gui.ellipse(ghost.x, ghost.y, 10, 10, 1, 0xffff00ff)
      gui.text(610, 580, string.format("%f ; %f", ghost.x, ghost.y))
   end
end

function onStartup()
   level = movie.getMovieFileName():match("/(%d+-%d+).*%.ltm$")
   ghostFilePath = "/home/ghosts/" .. level .. ".csv"
   loadGhost()
end
