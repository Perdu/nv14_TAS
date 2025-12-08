-- AI-generated
-- libTAS Lua Script
-- Starts unpaused (if needed), waits for first Space press, saves a state, pauses,
-- and permanently disables itself *per game session*.

local KEY_SPACE = 0x020        -- X11 keysym for Space
-- local KEY_S = 0x073            -- X11 keysym for s
local SAVE_SLOT = 1             -- Save slot number (1–10)
local ASSUME_STARTS_PAUSED = true  -- Set to false if your game starts unpaused

-- Session state
local done = false
local triggered = false
local need_unpause = false

local level = nil
local ghostFilePath = nil
local memy=""
local memspeed_y=""
local levels = dofile("/home/lua/levels.lua")
local dbg = true
local display_hitboxes = true
local display_ghost = true
local display_current_path = true

local ghostData = {}      -- frame → {x, y}
local space_frame = -100
local ramsearch_done = false
local max_x = 0
local max_y = 0

local path = {}
local knownFrames = {}   -- sorted list of frames already stored
local bestPath = {}
local door_x = nil
local door_y = nil

-- Insert or update path at a specific frame
local function recordFrame(frame, x, y)
    if not path[frame] then
        table.insert(knownFrames, frame)
        table.sort(knownFrames)
    end
    path[frame] = {x = x, y = y}
end

-- Convert r,g,b to 0xAARRGGBB color
local function rgb(r,g,b,a)
    a = a or 255
    return (a << 24) | (r << 16) | (g << 8) | b
end

function drawList(list, size, r, g, b)
   -- print(list)
   for _, e in ipairs(list) do
      gui.ellipse(e.x, e.y, size, size, 1, rgb(r, g, b))
   end
end

function display_distance_to_door(x, y, door_x, door_y)
   local dx = x - door_x
   local dy = y - door_y

   -- distance between the centers
   local center_dist = math.sqrt(dx*dx + dy*dy)

   -- subtract radii (player=10, door=12)
   local edge_dist = center_dist - (10 + 12)

    if edge_dist > 0 and edge_dist < 50 then
       -- draw the value on screen
       gui.text(door_x - 20, door_y + 10, string.format("%.2f", edge_dist), 0xffffff00)
    end
end

function draw_hitboxes()
      local data = levels[level]
      if not data then return end

      gui.ellipse(data.door_x, data.door_y, 12, 12)
      gui.ellipse(data.doorswitch_x, data.doorswitch_y, 6, 6)
      door_x = data.door_x
      door_y = data.door_y

      drawList(data.mines, 4, 255, 0, 0)         -- red mines
      -- drawList(data.drones, 9, 0, 0, 255)
      -- drawList(data.floorguards, 6, 0, 0, 0)
      drawList(data.gold, 6, 255, 255, 0)
      -- drawList(data.launchpads, 6, 255, 0, 255) -- magenta launchpads
      drawList(data.switches, 5, 0, 255, 255)    -- cyan switches
end

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

         -- gui.text(600, y, str, 0xff88ff88)  -- light green for future
      end
   end
end

function draw_velocity_arrows(x, y, vx, vy)
    -- scale speed so arrows stay readable
    local scale = 4     -- adjust if arrows feel too long/short
    local vertical_color = 0x88ff0000
    local horizontal_color = 0x880000ff

    -- horizontal arrow
    local hx = x + vx * scale
    gui.line(x, y, hx, y, horizontal_color)

    -- small arrowhead for horizontal
    if vx ~= 0 then
        local dir = (vx > 0) and 1 or -1
        gui.line(hx, y, hx - 4 * dir, y - 3, horizontal_color)
        gui.line(hx, y, hx - 4 * dir, y + 3, horizontal_color)
    end

    -- vertical arrow
    local vy_scaled = vy * scale
    local hy = y + vy_scaled
    gui.line(x, y, x, hy, vertical_color)

    -- arrowhead for vertical
    if vy ~= 0 then
        local dir = (vy > 0) and 1 or -1
        gui.line(x, hy, x - 3, hy - 4 * dir, vertical_color)
        gui.line(x, hy, x + 3, hy - 4 * dir, vertical_color)
    end

    -- Optional: draw numeric values
    gui.text(300, 575, string.format("vx: %f", vx), vertical_color, 0, 0, 15)
    gui.text(300, 585,  string.format("vy: %f", vy), horizontal_color, 0, 0, 15)
end

function onPaint()
   local x = -1
   local y = -1
   if memy ~= "" then
      local y_num = tonumber(memy, 16)
      y = memory.readd(y_num)
      local x_num = y_num - 56
      x = memory.readd(x_num)
      if display_hitboxes then
         gui.ellipse(x, y, 10, 10)
      end
      gui.text(150, 587, string.format("%f ; %f", x, y), 0xffffffff, 0, 0, 15)
      if door_x and door_y then
         display_distance_to_door(x, y, door_x, door_y)
      end
      if memspeed_y ~= "" then
         local y_num = tonumber(memspeed_y, 16)
         local vy = memory.readd(y_num)
         local x_num = y_num - 56
         local vx = memory.readd(x_num)
         draw_velocity_arrows(x, y, vx, vy)
      end
   end

   if display_hitboxes then
      draw_hitboxes()
   end

   local f = movie.currentFrame()
   if space_frame ~= - 100 then
      local ghost = ghostData[f - space_frame]
      if ghost then
         gui.ellipse(ghost.x, ghost.y, 10, 10, 1, 0xffff00ff)
         local ghost_text_position = 150
         local best_path_exists = bestPath[f]
         if best_path_exists then
            -- move ghost text to the left to display best path instead
            ghost_text_position = 320
         end
         gui.text(ghost_text_position, 575, string.format("%f ; %f", ghost.x, ghost.y), 0xffff00ff, 0, 0, 15)

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

      display_ghost_history(ghost, f)
   end

   if max_x > 0 and max_y > 0 then
      gui.ellipse(max_x, max_y, 10, 10, 1, 0xffffff00)
      -- draw position of best path
      local a = bestPath[f]
      if a then
         gui.ellipse(a.x, a.y, 1, 1, 1, 0xffffff00)
         gui.text(150, 575, string.format("%f ; %f", a.x, a.y), 0xffffff00, 0, 0, 15)
      end
   end

   if display_current_path then
      -- Draw line segments between consecutive stored frames
      for i = 1, #knownFrames do
         local fA = knownFrames[i]

         if fA >= f then break end   -- Do not go beyond current frame

         local a = path[fA]

         gui.ellipse(a.x, a.y, 1, 1, 1, 0xffffffff) -- purple-yellow dot
      end
      if x ~= -1 then
         gui.ellipse(x, y, 1, 1, 1, 0xffffffff) -- purple-yellow dot
      end
   end
end

-- This runs each time the game (process) starts.
function onStartup()
    -- Reset session variables (important when restarting the game)
    done = false
    triggered = false
    ramsearch_done = false
    space_frame = -100
    max_x = 0
    max_y = 0

    -- Request an unpause on first frame if needed
    need_unpause = ASSUME_STARTS_PAUSED

    ghostData = {}
    level = movie.getMovieFileName():match("/(%d+-%d+).*%.ltm$")
    ghostFilePath = "/home/ghosts/" .. level .. ".csv"
    loadGhost()

    path = {}
    bestPath = {}
    knownFrames = {}
    memy = ""
    memspeed_y = ""
    door_x = nil
    door_y = nil
end

-- Detect Space key press
function onInput()
    if input.getKey(KEY_SPACE) ~= 0 and memy ~= "" and not triggered then
       print("Position saved")
       local y_num = tonumber(memy, 16)
       local y = memory.readd(y_num)
       local x_num = y_num - 56
       local x = memory.readd(x_num)
       max_x = x
       max_y = y
       input.setKey(KEY_SPACE, 0)
       if movie.getMarker() ~= "" then
          movie.setMarker("best")
       end
       -- copy path into bestPath
       for frame, pos in pairs(path) do
          bestPath[frame] = { x = pos.x, y = pos.y }
       end
    end

    if display_current_path and memy ~= "" then
       local f = movie.currentFrame()
       local y_num = tonumber(memy, 16)
       local y = memory.readd(y_num)
       local x_num = y_num - 56
       local x = memory.readd(x_num)
       recordFrame(f, x, y)
    end

    if not done then
       if input.getKey(KEY_SPACE) ~= 0 then
          triggered = true
       end
    end
end

-- Perform runtime actions (must be done in onFrame)
function onFrame()
    -- Unpause at startup if requested
    if need_unpause then
        runtime.playPause()
        need_unpause = false
    end

    -- If Space was pressed, save and pause
    if triggered then
       space_frame = movie.currentFrame()
        runtime.saveState(SAVE_SLOT)
        if dbg then
           print(string.format("nb_results newsearch: %f", levels[level].n_y))
        end
        local i = ramsearch.newsearch(9, 0, 1, levels[level].n_y, "==")
        if dbg then
           print(string.format("nb_results newsearch: %d", i))
        end

        -- Disable for this session only
        done = true
        triggered = false
    end

   if not ramsearch_done then
      local f = movie.currentFrame()
      if f == space_frame + 1 then
         local i = ramsearch.search()
         if dbg then
            print(string.format("nb_results: %d", i))
         end
      elseif f == space_frame + 2 then
         local i = ramsearch.search(0, 0, "!=")
         if dbg then
            print(string.format("nb_results: %d", i))
         end
         if i == 1 then
            memy = ramsearch.get_address(j)
            print(string.format("memy: %s", memy))
         else
            print(string.format("Error: found too many values (%d)", i))
            if dbg then
               for j = 0,i-1,1
               do
                  local v = ramsearch.get_current_value(j)
                  local addr = ramsearch.get_address(j)
                  print(string.format("current value: %f @ %s", v, addr))
               end
            end
         end
         -- And now, speed
         i = ramsearch.newsearch(9, 0, 1, 0.14, ">")
         if dbg then
            print(string.format("nb_results newsearch speed: %d", i))
         end
         i = ramsearch.search(1, 0.16, "<")
         if dbg then
            print(string.format("nb_results search speed 2: %d", i))
         end
      elseif f == space_frame + 3 then
         local i = ramsearch.search(1, 0.29, ">")
         if dbg then
            print(string.format("nb_results search speed 3: %d", i))
         end
         i = ramsearch.search(1, 0.30, "<")
         if dbg then
            print(string.format("nb_results search speed 4: %d", i))
         end
         if i == 1 then
            memspeed_y = ramsearch.get_address(0)
            print(string.format("memspeed_y: %s", memspeed_y))
         else
            ramsearch_done = true
            runtime.loadState(SAVE_SLOT)
            runtime.playPause()
         end
      end
   end
end

-- Register callbacks
callback.onStartup(onStartup)
callback.onFrame(onFrame)
