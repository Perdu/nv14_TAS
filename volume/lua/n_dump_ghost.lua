-- AI-generated
-- libTAS Lua Script
-- Starts unpaused (if needed), waits for first Space press, saves a state, pauses,
-- and permanently disables itself *per game session*.

local KEY_SPACE = 0x020        -- X11 keysym for Space
local SAVE_SLOT = 1             -- Save slot number (1–10)
local ASSUME_STARTS_PAUSED = true  -- Set to false if your game starts unpaused

-- Session state
local done = false
local triggered = false
local need_unpause = false

local level = "04-0"
local memy=""
local levels = dofile("/home/lua/levels.lua")
local dbg = true

local space_frame = -100
local pos_found = false


function onPaint()
   if memy ~= "" then
      local y_num = tonumber(memy, 16)
      local y = memory.readd(y_num)
      local x_num = y_num - 56
      local x = memory.readd(x_num)
      cur_frame = movie.currentFrame()
      gui.text(150, 580, string.format("%f ; %f", x, y))
      print(string.format("%d,%f,%f", cur_frame, x, y))
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
      local f = movie.currentFrame()
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
end

-- Register callbacks
callback.onStartup(onStartup)
callback.onFrame(onFrame)
