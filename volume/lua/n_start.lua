-- Some parts are AI-generated
-- libTAS Lua Script

dofile("/home/lua/lib/utils.lua")
dofile("/home/lua/lib/hitboxes.lua")
dofile("/home/lua/lib/keysyms.lua")
dofile("/home/lua/lib/ghost.lua")
dofile("/home/lua/lib/speed.lua")
dofile("/home/lua/lib/drones.lua")
dofile("/home/lua/lib/bruteforcers/rcj.lua")
grounded_levels = dofile("/home/lua/data/grounded_levels.lua")
levels = dofile("/home/lua/data/levels.lua")

---- Parameters
dbg = true
display_hitboxes = true
draw_gold_hitboxes = false
display_ghost = true
display_current_path = true
display_ghost_moves_under_ghost = false
search_for_drones_position = true
display_drones_targets = false
display_drones_raycasts = true
MAX_DIST_RAYCAST_DISPLAY = 30
display_arrows = false
-- set the number of the drone you want removed (it will go through walls)
remove_drone = 0

---- Constants
SAVE_SLOT = 1             -- Save slot number (1–10)
ASSUME_STARTS_PAUSED = false  -- Set to false if your game starts unpaused
BRUTEFORCER_SAVESTATE = 7
GHOST_COLOR = 0xffff00ff
BEST_POSITION_COLOR = 0xffffff00

---- Session state
done = false
triggered = false
need_unpause = false
level = nil
ghostFilePath = nil
memy=""
memspeed_y=""
drones_memx = {}
drones_target_memx = {}
shift_pressed = false
original_input_modified = false
ghostData = {}      -- frame → {x, y}
space_frame = -100
pos_found = false
ramsearch_done = false
ramsearch_drones_done = false
advance_one_step_after_ramsearch = 2
max_x = 0
max_y = 0
path = {}
knownFrames = {}   -- sorted list of frames already stored
save_best_position = false
bruteforce_rcj = false
bestPath = {}
drones_candidates = {}

---- Callbacks

function onPaint()
   local x = -1
   local y = -1
   -- override episode name to be able to display info
   gui.rectangle(410, 577, 380, 22, 1, 0xff797988, 1)

   -- for placement during dev
   -- gui.text(315, 575, "toto", 0xffff2200, 0, 0, 15)
   -- gui.text(515, 585, "toto", GHOST_COLOR, 0, 0, 15)

   gui.text(760, 5, level)

   if memy ~= "" then
      x, y = get_player_position()
      if display_hitboxes then
         gui.ellipse(x, y, HITBOX_PLAYER, HITBOX_PLAYER)
      end
      gui.text(160, 587, string.format("%f ; %f", x, y), 0xffffffff, 0, 0, 15)
      data = levels[level]
      if data.doors then
         display_distance_to_doors(x, y, data.doors)
      end

      if levels[level].switches then
         display_distance_to_switches(x, y, levels[level].switches)
      end
      if memspeed_y ~= "" then
         local vx, vy = get_player_speed()
         local horizontal_color, vertical_color = get_speed_color(vx, vy)
         gui.text(310, 575, string.format("vx: %f", vx), horizontal_color, 0, 0, 15)
         gui.text(310, 585, string.format("vy: %f", vy), vertical_color, 0, 0, 15)
         if display_arrows then
            draw_velocity_arrows(x, y, vx, vy)
         end
      end
   end

   if display_hitboxes then
      draw_hitboxes()
   end

   local f = movie.currentFrame()
   if space_frame ~= - 100 then
      local ghost = ghostData[f - space_frame]
      if ghost then
         gui.ellipse(ghost.x, ghost.y, HITBOX_PLAYER, HITBOX_PLAYER, 1, GHOST_COLOR)
         local ghost_text_position = 160
         local best_path_exists = bestPath[f]
         if best_path_exists then
            -- move ghost text to the right to display best path instead
            ghost_text_position = 600
         end
         gui.text(ghost_text_position, 575, string.format("%f ; %f", ghost.x, ghost.y), GHOST_COLOR, 0, 0, 15)
         -- speed
         gui.text(415, 575, string.format("vx: %f", ghost.vx), GHOST_COLOR, 0, 0, 15)
         gui.text(415, 585, string.format("vy: %f", ghost.vy), GHOST_COLOR, 0, 0, 15)
         if display_ghost_moves_under_ghost then
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

      display_ghost_history(ghost, f)
   end

   if max_x > 0 and max_y > 0 then
      gui.ellipse(max_x, max_y, HITBOX_PLAYER, HITBOX_PLAYER, 1, BEST_POSITION_COLOR)
      -- draw position of best path
      local a = bestPath[f]
      if a then
         gui.ellipse(a.x, a.y, 1, 1, 1, BEST_POSITION_COLOR)
         gui.text(160, 575, string.format("%f ; %f", a.x, a.y), BEST_POSITION_COLOR, 0, 0, 15)
      end
   end

   if bestPath[f] then
      print(bestPath)
      gui.text(505, 575, string.format("vx: %f", bestPath[f].vx), BEST_POSITION_COLOR, 0, 0, 15)
      gui.text(505, 585, string.format("vy: %f", bestPath[f].vy), BEST_POSITION_COLOR, 0, 0, 15)
   end

   -- display help comparison to either ghost or best path
   -- we can only compare 5 first digits as the full value isn't dumped to file
   compare = nil
   if bestPath[f] then
      compare = bestPath[f]
   elseif space_frame ~= -100 and ghostData[f - space_frame]  then
      compare = ghostData[f - space_frame]
   end
   if compare then
      if float_eq(compare.x, x, 1e-5) then
         sign = "="
      elseif compare.x > x then
         sign = "<"
      else
         sign = ">"
      end
      gui.text(140, 587, sign, 0xffffffff, 0, 0, 15)
      if float_eq(compare.y, y, 1e-5) then
         sign = "="
      elseif compare.y > y then
         sign = "^"
      else
         sign = "v"
      end
      gui.text(150, 587, sign, 0xffffffff, 0, 0, 15)
   end

   if display_current_path then
      -- Draw line segments between consecutive stored frames
      for i = 1, #knownFrames do
         local fA = knownFrames[i]

         if fA >= f then break end   -- Do not go beyond current frame

         local a = path[fA]

         gui.ellipse(a.x, a.y, 1, 1, 1, 0x55ffffff)
      end
      if x ~= -1 then
         gui.ellipse(x, y, 1, 1, 1, 0x55ffffff)
      end
   end

   if not ramsearch_done then
      gui.text(80, 580, "Waiting...")
   end

   if advance_one_step_after_ramsearch == 3 then
      advance_one_step_after_ramsearch = advance_one_step_after_ramsearch + 1
      gui.text(80, 580, "Loaded.", 0xff00ff00)
    end

   display_drones_number()
end


function onStartup()
    -- Reset session variables (important when restarting the game)
    done = false
    triggered = false
    pos_found = false
    ramsearch_done = false
    ramsearch_drones_done = false
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
    bestPath_speed = {}
    knownFrames = {}
    memy = ""
    memspeed_y = ""
    drones_memx = {}
    drones_target_memx = {}
    drones_candidates = {}

    bruteforce_rcj = false
end


function onInput()
    if input.getKey(KEY_SPACE) ~= 0 and memy ~= "" and not triggered and movie.currentFrame() ~= space_frame - 1 then
       input.setKey(KEY_SPACE, 0)
       -- if movie.getMarker() ~= "" then
       --    movie.setMarker("best")
       -- end
       -- do it on next frame so it's on the savestate frame
       save_best_position = true
    end

    if input.getKey(KEY_r) ~= 0 and memy ~= "" then
       bruteforce_rcj_x = true
    end
    if bruteforce_rcj_x then
       rcj("x")
    end

    if display_current_path and memy ~= "" then
       local f = movie.currentFrame()
       local x, y = get_player_position()
       local vx, vy = get_player_speed()
       recordFrame(f, x, y, vx, vy)
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
         advance_one_step_after_ramsearch = advance_one_step_after_ramsearch + 1
         runtime.playPause()
      end
   end

   if save_best_position then
      local x, y = get_player_position()
      local vx, vy = get_player_speed()
      max_x = x
      max_y = y

       -- copy path into bestPath
       for frame, pos in pairs(path) do
          -- print(string.format("%d: %f ; %f", frame, pos.x, pos.y))
          bestPath[frame] = { x = pos.x, y = pos.y, vx = pos.vx, vy = pos.vy }
       end
       -- current frame
       bestPath[movie.currentFrame()] = { x = x, y = y, vx = vx, vy = vy }
       print("Position saved")

      runtime.saveState(10)
      save_best_position = false
   end

   dofile("/home/lua/lib/n_position_ramsearch.lua")
end
