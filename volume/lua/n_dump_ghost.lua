-- AI-generated
-- libTAS Lua Script
-- Starts unpaused (if needed), waits for first Space press, saves a state, pauses,
-- and permanently disables itself *per game session*.

local KEY_SPACE = 0x020        -- X11 keysym for Space
local KEY_LEFT  = 0xff51   -- XK_Left
local KEY_RIGHT = 0xff53   -- XK_Right
local KEY_SHIFT = 0xffe1   -- XK_Shift_L (or 0xffe2 for right shift)
local SAVE_SLOT = 1             -- Save slot number (1–10)
local ASSUME_STARTS_PAUSED = true  -- Set to false if your game starts unpaused

-- Session state
local done = false
local triggered = false
local need_unpause = false

local level = nil
local memy=""
local levels = dofile("/home/lua/levels.lua")
local dbg = true
local ghostFilePath = nil
local ghostFile = nil

local space_frame = -100
local pos_found = false
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
         pos_found = true
         runtime.loadState(SAVE_SLOT)
      end
   end

   if pos_found then
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

            print(string.format("%d,%f,%f,%d,%d,%d", f, x, y, shift, left, right))
            ghostFile:write(string.format("%d,%f,%f,%d,%d,%d\n", f - space_frame, x, y, shift, left, right))
         end
      end
   end

   if f == movie.frameCount() then
      -- libTAS automatically stop there, but we need one more frame
      runtime.playPause()
   end

   -- close ghost file at the end of the movie
   -- still keep a bit more frames as it's usually cut beforehand
   if f > movie.frameCount() + 3 then
      ghostFile:close()
      runtime.playPause()
      print("Closed ghost file.")
   end
end
