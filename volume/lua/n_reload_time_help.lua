-- This was another script I used to find loading time of each level

-- CONFIGURATION -----------------------------------
local trigger_key = 32              -- Space key
local addr_check = 0x5639bae6f760
local expected_value = 655360            -- correct value
-- otherwise it's 524288
local advance_frames = 5            -- frames to advance before checking
local empty_check_length = 10       -- how many previous frames must be empty
local first_slot = 2                -- first savestate slot
local last_slot = 10                -- last savestate slot
----------------------------------------------------

local prev_key_state = false
local check_in_progress = false
local target_frame = 0
local current_slot = first_slot

function on_frame()
    local f = movie.currentFrame()
    local key_down = (input.getKey(trigger_key) == 1)
    local key_pressed = key_down and not prev_key_state
    prev_key_state = key_down

    -- When Space is freshly pressed
    if key_pressed then
        local marker = movie.getMarker()
        if marker ~= none then
           print(marker)

           runtime.saveState(current_slot)
           print(string.format("[libTAS] Saved state to slot %d at frame %d", current_slot, f))
           current_slot = current_slot + 1
            if current_slot > last_slot then
                current_slot = 2
            end

           -- Schedule check a few frames later
           target_frame = f + advance_frames
           check_in_progress = true
        end
    end

    -- When we reach the target frame, perform the memory check
    if check_in_progress and f >= target_frame then
        local val = memory.reads32(addr_check)
        -- print(string.format("[libTAS] Checking memory (addr=0x%X) value=%d expected=%d", addr_check, val, expected_value))

        if val ~= expected_value then
            print("[libTAS] Value incorrect — reloading previous state and pausing playback")
            local reload_slot = (current_slot == 2) and last_slot or (current_slot - 1)
            runtime.loadState(reload_slot)
            runtime.playPause()  -- pause
        else
            print("[libTAS] Value OK — continuing playback")
        end

        check_in_progress = false
    end
end

callback.onFrame(on_frame)
