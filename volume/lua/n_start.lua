-- AI-generated
-- libTAS Lua Script
-- Starts unpaused (if needed), waits for first Space press, saves a state, pauses,
-- and permanently disables itself *per game session*.

KEY_SPACE = 0x020        -- X11 keysym for Space
-- KEY_S = 0x073            -- X11 keysym for s
KEY_SHIFT = 0xffe1
SAVE_SLOT = 1             -- Save slot number (1–10)
ASSUME_STARTS_PAUSED = false  -- Set to false if your game starts unpaused

-- Session state
done = false
triggered = false
need_unpause = false

level = nil
ghostFilePath = nil
memy=""
memspeed_y=""
levels = dofile("/home/lua/levels.lua")
dofile("/home/lua/lib/grounded_levels.lua")
shift_pressed = false
original_input_modified = false
dbg = true
display_hitboxes = true
draw_gold_hitboxes = false
display_ghost = true
display_current_path = true

ghostData = {}      -- frame → {x, y}
space_frame = -100
pos_found = false
ramsearch_done = false
advance_one_step_after_ramsearch = 2
max_x = 0
max_y = 0
save_best_position = false

path = {}
knownFrames = {}   -- sorted list of frames already stored
bestPath = {}
door_x = nil
door_y = nil

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
      if draw_gold_hitboxes then
         drawList(data.gold, 6, 255, 255, 0)
      end
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
    local horizontal_color = 0xffff0000
    local vertical_color = 0xff0000ff
    if vy >= 7.00 or vy <= -7.00 then
       vertical_color = 0xffff0000
    end

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
    if vy >= 7.00 or vy <= -7.00 then
       gui.line(x - 1, y, x - 1, hy, vertical_color)
       gui.line(x + 1, y, x + 1, hy, vertical_color)
    end

    -- arrowhead for vertical
    if vy ~= 0 then
        local dir = (vy > 0) and 1 or -1
        gui.line(x, hy, x - 3, hy - 4 * dir, vertical_color)
        gui.line(x, hy, x + 3, hy - 4 * dir, vertical_color)
    end

    -- Optional: draw numeric values
    gui.text(300, 575, string.format("vx: %f", vx), horizontal_color, 0, 0, 15)
    gui.text(300, 585,  string.format("vy: %f", vy), vertical_color, 0, 0, 15)
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
            -- move ghost text to the right to display best path instead
            ghost_text_position = 400
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

   if not ramsearch_done then
      gui.text(120, 580, "Waiting...")
   end

   -- if advance_one_step_after_ramsearch == 2 then
   --   gui.text(120, 580, "Go!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
   -- end
end

-- This runs each time the game (process) starts.
function onStartup()
    -- Reset session variables (important when restarting the game)
    done = false
    triggered = false
    pos_found = false
    ramsearch_done = false
    advance_one_step_after_ramsearch = 2
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
       input.setKey(KEY_SPACE, 0)
       -- if movie.getMarker() ~= "" then
       --    movie.setMarker("best")
       -- end
       -- do it on next frame so it's on the savestate frame
       save_best_position = true
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

    if not ramsearch_done and grounded_levels[level] and not original_input_modified then
       local f = movie.currentFrame()
       if f == space_frame then
          shift_pressed = input.getKey(KEY_SHIFT)
          print(string.format("Shift pressed? %d", shift_pressed))
          input.setKey(KEY_SHIFT, 1)
          original_input_modified = true
       end
    elseif ramsearch_done and grounded_levels[level] and original_input_modified then
       runtime.playPause()
       if movie.currentFrame() == space_frame then
          -- put original value back
          print("Putting back shift value:", shift_pressed)
          input.setKey(KEY_SHIFT, shift_pressed)
          original_input_modified = false
          runtime.loadState(SAVE_SLOT)
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

   if advance_one_step_after_ramsearch < 2 then
      advance_one_step_after_ramsearch = advance_one_step_after_ramsearch + 1
      if advance_one_step_after_ramsearch == 2 then
         runtime.playPause()
      end
   end

   if save_best_position then
       local y_num = tonumber(memy, 16)
       local y = memory.readd(y_num)
       local x_num = y_num - 56
       local x = memory.readd(x_num)
       max_x = x
       max_y = y

       -- copy path into bestPath
       for frame, pos in pairs(path) do
          -- print(string.format("%d: %f ; %f", frame, pos.x, pos.y))
          bestPath[frame] = { x = pos.x, y = pos.y }
       end
       -- current frame
       bestPath[movie.currentFrame()] = { x = x, y = y }
       print("Position saved")

      runtime.saveState(10)
      save_best_position = false
   end

   dofile("/home/lua/lib/n_position_ramsearch.lua")
end

-- Register callbacks
callback.onStartup(onStartup)
callback.onFrame(onFrame)
