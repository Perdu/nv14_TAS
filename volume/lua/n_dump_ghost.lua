-- AI-generated
-- libTAS Lua Script
-- Starts unpaused (if needed), waits for first Space press, saves a state, pauses,
-- and permanently disables itself *per game session*.

local KEY_SPACE = 0x020        -- X11 keysym for Space
local KEY_LEFT  = 0xff51   -- XK_Left
local KEY_RIGHT = 0xff53   -- XK_Right
local KEY_SHIFT = 0xffe1   -- XK_Shift_L (or 0xffe2 for right shift)
local SAVE_SLOT = 1             -- Save slot number (1–10)
local ASSUME_STARTS_PAUSED = false  -- Set to false if your game starts unpaused

-- Session state
local done = false
local triggered = false
local need_unpause = false

local level = nil
local memy=""
local memspeed_y=""
local levels = dofile("/home/lua/levels.lua")
local dbg = true
local ghostFilePath = nil
local ghostFile = nil

local space_frame = -100
local pos_found = false
local ramsearch_done = false
local pre_reload_skipped = false

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
    if done then return end

    if input.getKey(KEY_SPACE) ~= 0 then
        triggered = true
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
       if not pos_found then
          if f == space_frame + 1 then
             local i = ramsearch.search()
             if dbg then
                print(string.format("nb_results: %d", i))
                for j = 0,i-1,1
                do
                   local v = ramsearch.get_current_value(j)
                   print(string.format("current value: %f", v))
                end
             end
          elseif f == space_frame + 2 then
             local i = ramsearch.search(0, 0, "!=")
             if dbg then
                print(string.format("nb_results: %d", i))
             end
             if i == 1 then
                memy = ramsearch.get_address(j)
                pos_found = true
             else
                print(string.format("Error: found too many values (%d)", i))
                for j = 0,i-1,1
                do
                   local v = ramsearch.get_current_value(j)
                   local addr = ramsearch.get_address(j)
                   local addr_x = tonumber(addr, 16) - 56
                   local x = memory.readd(addr_x)
                   if dbg then
                      print(string.format("Value %d: %f @%s", j, v, addr))
                      print(string.format("Corresponding x value @%s : %f", addr_x, x))
                   end
                   if x == levels[level].n_x then
                      -- we finally found the right one
                      memy = ramsearch.get_address(j)
                      print("Found!")
                      pos_found = true
                      break
                   end
                end
             end
          end
       end
       -- And now, speed
       if f == space_frame + 2 then
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
          end
          ramsearch_done = true
          runtime.loadState(SAVE_SLOT)
          advance_one_step_after_ramsearch = 0
       end
    end

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
