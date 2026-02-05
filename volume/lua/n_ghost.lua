-- AI-generated
-- ==============================
-- Ghost display for libTAS
-- Reads CSV and draws 10px circle
-- + There's a parameter to display the ghost path
-- ==============================

dofile("lua/lib/keysyms.lua")
dofile("lua/lib/ghost.lua")

---- Parameters
display_ghost_path = false
display_ghost_full_path = false
display_history = false
display_inputs = false
display_position = false

---- Session state
ghostData = {}
level = nil
ghostFilePath = nil
sortedFrames = {}   -- ordered list of frame numbers
space_frame = -100
triggered = false
case = ""


function onPaint()
   local f = movie.currentFrame()
   if triggered then
      if case == "combined" then
         i = f - 1
      else
         i = f - space_frame
      end
      local ghost = ghostData[i]
      if ghost then
         gui.ellipse(ghost.x, ghost.y, 10, 10, 1, 0xffff00ff)

         if display_position then
            gui.text(590, 580, string.format("%f ; %f", ghost.x, ghost.y), 0xffff00ff)
         end

         if display_inputs then
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

      if display_history then
         display_ghost_history(ghost, f)
      end

      if display_ghost_path then
         if display_ghost_full_path then
            limit = #sortedFrames - 1
         else
            limit = f - 1 - space_frame
         end

         for i = 1, limit do
            local a = ghostData[sortedFrames[i]]
            local b = ghostData[sortedFrames[i+1]]
            gui.line(a.x, a.y, b.x, b.y, 0xffff00ff)
         end
      end
   end
end

function onInput()
    if not triggered and input.getKey(KEY_SPACE) ~= 0 then
       space_frame = movie.currentFrame() + 1
       triggered = true
    end
end

function onStartup()
   ltmfile = movie.getMovieFileName()
   if ltmfile == "/home/n_speedrun.ltm" then
      case = "combined"
      ghostFilePath = "/home/n_recomp_rta_speedrun_ghost.csv"
      triggered = true
   else
      case = "level"
      level = movie.getMovieFileName():match("/(%d+-%d+).*%.ltm$")
      ghostFilePath = "/home/ghosts/" .. level .. ".csv"
   end
   loadGhost()
   space_frame = -100
   triggered = false
end
