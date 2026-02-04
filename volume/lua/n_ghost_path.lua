-- AI-generated
-- ==============================
-- Ghost path display for libTAS
-- Full line always, dots up to current frame
-- ==============================

dofile("/home/lua/lib/keysyms.lua")
dofile("/home/lua/lib/ghost.lua")

ghostData = {}      -- frame → {x, y}
level = nil
ghostFilePath = nil
sortedFrames = {}   -- ordered list of frame numbers
space_frame = -100
triggered = false
display_ghost_full_path = true

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
    if triggered then
--       for i = 1, #sortedFrames do
--          local frame = sortedFrames[i]
--          if frame > f then
--             break   -- stop once we pass current frame
--          end
--
--          local p = ghostData[frame - space_frame]
--
--          -- round to nearest pixel (required for gui.pixel)
--          local x = math.floor(p.x + 0.5)
--          local y = math.floor(p.y + 0.5)
--
--          gui.ellipse(p.x, p.y, 1, 1, 1, 0xffffff00) -- yellow dot
--       end

       -- Optional: display ghost coords at current frame
       local ghost = ghostData[f - space_frame]
       if ghost then
          gui.text(610, 580, string.format("%f ; %f", ghost.x, ghost.y))
          gui.ellipse(ghost.x, ghost.y, 1, 1, 1, 0xffffff00) -- yellow dot
       end
    end
end

function onInput()
    if not triggered and input.getKey(KEY_SPACE) ~= 0 then
       space_frame = movie.currentFrame()
       triggered = true
    end
end

-- ------------------------------
-- Startup: detect level and load CSV
-- ------------------------------
function onStartup()
    level = movie.getMovieFileName():match("/(%d+-%d+).*%.ltm$")
    ghostFilePath = "/home/ghosts/" .. level .. ".csv"
    loadGhost()
    space_frame = -100
    triggered = false
end
