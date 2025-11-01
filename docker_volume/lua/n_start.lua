-- AI-generated
-- libTAS Lua Script
-- Behavior:
--   * If ASSUME_STARTS_PAUSED = true, unpause on the first onFrame() call.
--   * Wait for the first Space press.
--   * Save state to slot SAVE_SLOT, pause, and permanently disable script.

local ASSUME_STARTS_PAUSED = true
local SAVE_SLOT = 1

-- Keycode for Space (X11 keysym). If this doesn't match your environment,
-- try 0x040 (SDL) or print input.getKey codes to debug.
local KEY_SPACE = 0x020

local done = false         -- script completed and disabled forever
local triggered = false    -- space detected this frame
local need_unpause = false -- request to unpause on first frame

-- onStartup: request an unpause if we assume the emulator starts paused.
-- We don't call runtime.playPause() here because runtime functions must
-- be executed in onFrame() to reliably affect the current frame.
function onStartup()
    if ASSUME_STARTS_PAUSED then
        need_unpause = true
    end
end

-- onInput: detect Space press (called each input decision)
function onInput()
    if done then return end
    if input.getKey(KEY_SPACE) ~= 0 then
        triggered = true
    end
end

-- onFrame: do runtime actions here
function onFrame()
    if done then return end

    -- If we asked to unpause at startup, do it here (on the first frame)
    if need_unpause then
        runtime.playPause()   -- toggle pause -> unpause (assumes start paused)
        need_unpause = false
        -- continue without returning; we still want to be able to detect Space this same run
    end

    if triggered then
        -- One-time actions (performed in onFrame as required)
        runtime.saveState(SAVE_SLOT)
        runtime.playPause()  -- pause the game

        -- Permanently disable the script so it never triggers again
        done = true
        triggered = false

        -- Optionally remove callbacks to avoid any further overhead
        -- (libTAS doesn't expose a 'remove callback' in the API here, but marking done is enough)
    end
end

-- Register callbacks
callback.onStartup(onStartup)
callback.onInput(onInput)
callback.onFrame(onFrame)
