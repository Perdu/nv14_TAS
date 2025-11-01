-- AI-generated
-- libTAS Lua Script
-- Advances until the first Space press, creates a savestate, pauses, and then disables itself.

local KEY_SPACE = 0x020  -- X11 keysym for Space
local triggered = false   -- Has the event already happened?
local done = false        -- Has the script completed and disabled itself?

function onInput()
    if done then return end

    -- Check if Space is pressed this frame
    if input.getKey(KEY_SPACE) ~= 0 then
        triggered = true
    end
end

function onFrame()
    if done then return end

    if triggered then
        -- Perform the one-time actions
        runtime.saveState(1)
        runtime.playPause()

        -- Prevent further triggers permanently
        done = true
        triggered = false
    end
end

-- Register the callbacks
callback.onInput(onInput)
callback.onFrame(onFrame)
