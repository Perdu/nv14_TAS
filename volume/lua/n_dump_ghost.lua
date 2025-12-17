-- AI-generated
-- libTAS Lua Script
-- Starts unpaused (if needed), waits for first Space press, saves a state, pauses,
-- and permanently disables itself *per game session*.

KEY_SPACE = 0x020        -- X11 keysym for Space
KEY_LEFT  = 0xff51   -- XK_Left
KEY_RIGHT = 0xff53   -- XK_Right
KEY_SHIFT = 0xffe1   -- XK_Shift_L (or 0xffe2 for right shift)
SAVE_SLOT = 1             -- Save slot number (1–10)
ASSUME_STARTS_PAUSED = false  -- Set to false if your game starts unpaused

-- Session state
done = false
triggered = false
need_unpause = false

level = nil
memy=""
memspeed_y=""
levels = dofile("/home/lua/levels.lua")
dofile("/home/lua/lib/grounded_levels.lua")
shift_pressed = false
original_input_modified = false
dbg = true
ghostFilePath = nil
ghostFile = nil

space_frame = -100
pos_found = false
ramsearch_done = false
pre_reload_skipped = false

function onPaint()
   if memy ~= "" then
      local y_num = tonumber(memy, 16)
      local y = memory.readd(y_num)
      local x_num = y_num - 56
      local x = memory.readd(x_num)
      gui.text(150, 580, string.format("%f ; %f", x, y))
   end
end

-- This runs each time the game (process) starts.
function onStartup()
    -- Reset session variables (important when restarting the game)
    done = false
    triggered = false
    pos_found = false

    -- Request an unpause on first frame if needed
    need_unpause = ASSUME_STARTS_PAUSED

    memy = ""
    memspeed_y = ""
    level = movie.getMovieFileName():match("/(%d+-%d+).*%.ltm$")
    ghostFilePath = "/home/ghosts/" .. level .. ".csv"
    ghostFile = io.open(ghostFilePath, "w")
end

-- Detect Space key press
function onInput()

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
          movie.playPause()
       end
    elseif ramsearch_done and grounded_levels[level] and original_input_modified then
       if movie.currentFrame() == space_frame then
          -- put original value back
          print("Putting back shift value:", shift_pressed)
          input.setKey(KEY_SHIFT, shift_pressed)
          original_input_modified = false
       end
    end

end

-- Perform runtime actions (must be done in onFrame)
function onFrame()
   local f = movie.currentFrame()

    -- Unpause at startup if requested
    if need_unpause then
        runtime.playPause()
        need_unpause = false
    end

   dofile("/home/lua/lib/n_position_ramsearch.lua")

   if ramsearch_done then
      if not pre_reload_skipped then
         -- since onPaint() is called on the start + 2 frame before
         -- the reload, we need to skip this frame to avoid
         -- displaying it
         pre_reload_skipped = true
      else
         if memy ~= "" then
            local y_num = tonumber(memy, 16)
            local y = memory.readd(y_num)
            local x_num = y_num - 56
            local x = memory.readd(x_num)
            -- read keys
            local shift = (input.getKey(KEY_SHIFT) ~= 0) and 1 or 0
            local left  = (input.getKey(KEY_LEFT)  ~= 0) and 1 or 0
            local right = (input.getKey(KEY_RIGHT) ~= 0) and 1 or 0
            -- speed
            local y_num_speed = tonumber(memspeed_y, 16)
            local vy = memory.readd(y_num_speed)
            local x_num_speed = y_num_speed - 56
            local vx = memory.readd(x_num_speed)

            print(string.format("%d,%f,%f,%d,%d,%d,%f,%f", f, x, y, shift, left, right, vx, vy))
            ghostFile:write(string.format("%d,%f,%f,%d,%d,%d,%f,%f\n", f - space_frame, x, y, shift, left, right, vx, vy))
         end
      end
   end

   -- close ghost file at the end of the movie
   if f >= movie.frameCount() then
      ghostFile:close()
      print("Closed ghost file.")
   end
end
