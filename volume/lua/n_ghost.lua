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
local display_history = false
local display_inputs = false
local display_position = false

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

function display_ghost_history(ghost, f)
   -- vertical offset for listing
   local baseY = 150
   local lineH = 14
   local rel = f - space_frame
   local fontsize = 14
   local ghost_hist_x = 771
   -- ---- PREVIOUS 10 FRAMES ----
   for i = 10, 1, -1 do
      local gf = ghostData[rel - i]
      if gf then
         local y = baseY + (10 - i) * lineH
         color = (gf.shift == 1) and 0xff8888ff or 0xff000000
         gui.text(ghost_hist_x, y, "J", color, 0, 0, fontsize)

         color = (gf.left == 1) and 0xff8888ff or 0xff000000
         gui.text(ghost_hist_x + 8, y, "<", color, 0, 0, fontsize)

         color = (gf.right == 1) and 0xff8888ff or 0xff000000
         gui.text(ghost_hist_x + 15, y, ">", color, 0, 0, fontsize)
      end
   end
   -- ---- CURRENT FRAME ----
   local gf = ghostData[rel]
   if gf then
      local y = baseY + 11 * lineH
      color = (gf.shift == 1) and 0xffffffff or 0xff000000
      gui.text(ghost_hist_x, y, "J", color, 0, 0, fontsize)

      color = (gf.left == 1) and 0xffffffff or 0xff000000
      gui.text(ghost_hist_x + 8, y, "<", color, 0, 0, fontsize)

      color = (gf.right == 1) and 0xffffffff or 0xff000000
      gui.text(ghost_hist_x + 15, y, ">", color, 0, 0, fontsize)
   end
   -- ---- NEXT 10 FRAMES ----
   for i = 1, 10 do
      local gf = ghostData[rel + i]
      if gf then
         local y = baseY + (11 + i + 1) * lineH
         color = (gf.shift == 1) and 0xff88ff88 or 0xff000000
         gui.text(ghost_hist_x, y, "J", color, 0, 0, fontsize)

         color = (gf.left == 1) and 0xff88ff88 or 0xff000000
         gui.text(ghost_hist_x + 8, y, "<", color, 0, 0, fontsize)

         color = (gf.right == 1) and 0xff88ff88 or 0xff000000
         gui.text(ghost_hist_x + 15, y, ">", color, 0, 0, fontsize)
      end
   end
end

function onPaint()
   local f = movie.currentFrame()
   if triggered then
      local ghost = ghostData[f - space_frame]
      if ghost then
         gui.ellipse(ghost.x, ghost.y, 10, 10, 1, 0xffff00ff)

         if display_position then
            gui.text(590, 580, string.format("%f ; %f", ghost.x, ghost.y), 0xffff00ff)
         end

         if display_inputs then
            if ghost.shift == 1 then
               gui.text(ghost.x - 14, ghost.y + 13, "J", 0xffffffff)
            end
            if ghost.left == 1 then
               gui.text(ghost.x - 4, ghost.y + 13, "<", 0xffffffff)
            end
            if ghost.right == 1 then
               gui.text(ghost.x + 6, ghost.y + 13, ">", 0xffffffff)
            end
         end
      end

      if display_history then
         display_ghost_history(ghost, f)
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
