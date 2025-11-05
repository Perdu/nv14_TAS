-- This script computes the loading time of each level by detecting
-- when a variable in memory passes from a certain value when loading
-- the level to another value when loaded.
-- To find that variable address, use RAM search. Look for a value
-- usually equal to 99, and switching to 0 on the frame a level is
-- loaded.

-- CONFIGURATION -----------------------------------
local addr_ready = 0x55bd58170f40  -- 0x55b80c7dc710
local ready_value = 0            -- value indicating "ready" (adjust for your game)
local trigger_key = 32      -- space
----------------------------------------------------

local reset = false
local debug = false
local measuring = false
local start_frame = 0
local last_value = nil
local result_logged = false

function check_load_delay()
    local f = movie.currentFrame()

    if reset then
       start_frame = 1
       measuring = false
    end

    -- print(string.format("%s", measuring))
    if f < start_frame then
       print("Movie rewinded, stopping measurement.")
       measuring = false
    end

    -- Start measurement when Space is pressed
    if input.getKey(trigger_key) == 1 and not measuring and memory.reads16(addr_ready) ~= ready_value then
        measuring = true
        result_logged = false
        start_frame = f
        last_value = memory.reads16(addr_ready)
        if debug then
           print(string.format("[libTAS] Started measurement at frame %d (initial value = %d)", f, last_value))
        end
    end

    -- When measuring, check if the ready flag changes
    if measuring and not result_logged then
        local current = memory.reads16(addr_ready)
        if current == ready_value and current ~= last_value then
            local frames_waited = f - start_frame
            if debug then
               print(string.format("[libTAS] Level became ready after %d frames (frame %d → %d)",
                                   frames_waited, start_frame, f))
            end
            print(string.format("%d", frames_waited))
            result_logged = true
            measuring = false
        end
        last_value = current
    end
end

callback.onFrame(check_load_delay)
