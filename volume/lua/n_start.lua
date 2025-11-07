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

-- This runs each time the game (process) starts.
function onStartup()
    -- Reset session variables (important when restarting the game)
    done = false
    triggered = false

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
    if done then return end

    -- check_space()

    -- Unpause at startup if requested
    if need_unpause then
        runtime.playPause()
        need_unpause = false
    end

    -- If Space was pressed, save and pause
    if triggered then
        runtime.saveState(SAVE_SLOT)
        runtime.playPause()

        -- Disable for this session only
        done = true
        triggered = false
    end
end

-- Register callbacks
callback.onStartup(onStartup)
callback.onFrame(onFrame)
