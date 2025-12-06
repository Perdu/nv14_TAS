-- AI-generated
-- ==============================
-- Ghost display for libTAS
-- Reads CSV and draws 10px circle
-- ==============================

local ghostData = {}      -- frame → {x, y}
local level = nil
local ghostFilePath = nil
local space_frame = -100
local triggered = false

local KEY_SPACE = 0x020        -- X11 keysym for Space

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
        local frame, x, y, shift, left, right = line:match("(%d+),([^,]+),([^,]+),([^,]+),([^,]+),([^,]+)")
        if frame and x and y then
           ghostData[tonumber(frame)] = {
              x = tonumber(x),
              y = tonumber(y),
              shift = tonumber(shift),
              left = tonumber(left),
              right = tonumber(right)
           }
        end
    end

    file:close()
    print("Ghost loaded: " .. tostring(#ghostData) .. " frames")
end

function onPaint()
   local f = movie.currentFrame()
   if triggered then
      local ghost = ghostData[f - space_frame]
      if ghost then
         gui.ellipse(ghost.x, ghost.y, 10, 10, 1, 0xffff00ff)
         gui.text(590, 580, string.format("%f ; %f", ghost.x, ghost.y))

         if ghost.shift == 1 then
            color = 0xffffffff
         else
            color = 0xff000000
         end
         gui.text(760, 580, "J", color)
         gui.text(ghost.x - 14, ghost.y + 13, "J", color)

         if ghost.left == 1 then
            color = 0xffffffff
         else
            color = 0xff000000
         end
         gui.text(770, 580, "<", color)
         gui.text(ghost.x - 4, ghost.y + 13, "<", color)

         if ghost.right == 1 then
            color = 0xffffffff
         else
            color = 0xff000000
         end
         gui.text(780, 580, ">", color)
         gui.text(ghost.x + 6, ghost.y + 13, ">", color)
      end
   end
end

function onFrame()
    if not triggered and input.getKey(KEY_SPACE) ~= 0 then
       space_frame = movie.currentFrame()
       triggered = true
    end
end

function onStartup()
   level = movie.getMovieFileName():match("/(%d+-%d+).*%.ltm$")
   ghostFilePath = "/home/ghosts/" .. level .. ".csv"
   loadGhost()
   space_frame = -100
   triggered = false
end
