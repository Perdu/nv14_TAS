bruteforce_rcj = false
state_rcj = nil
rcj_not_found = true
rcj_frame = nil
NB_FUTURE_FRAME = 60
direction = nil
max_pos = nil
next_state = nil

-- optim: x or y
function rcj(optim)
   local direction

--   if not bruteforce_rcj then
--      return
--   end

   if state_rcj == nil then
      print("Starting to bruteforce rcj")
      if input.getKey(KEY_LEFT) ~= 0 then
         direction = "right"
      else
         direction = "left"
      end
      print(direction)
      state_rcj = "searching_for_jump_frame"
      runtime.saveState(BRUTEFORCER_SAVESTATE)
   elseif state_rcj == "searching_for_jump_frame" then
      if input.getKey(KEY_SHIFT) ~= 0 then
         rcj_frame = movie.currentFrame()
         rcj_not_found = false
         print("Found rcj frame")
         state_rcj = "looking_for_res"
         next_state = "try_holding_dirs"
      else
         -- keep searching
         return
      end
   elseif state_rcj == "looking_for_res" then
      local f = movie.currentFrame()
      if f == rcj_frame + NB_FUTURE_FRAME then
         local x, y = get_player_position()
         if max_pos == nil then
            if optim == "x" then
               max_pos = x
            else
               max_pos = y
            end
            print(string.format("Saving best %s position: %f", optim, max_pos))
         else
            if optim == "x" then
               if (direction == "right" and x > max_pos)
                  or (direction == "left" and x < max_pos) then
                  max_pos = x
                  print(string.format("Found better x pos: %f", max_pos))
               end
            else
               if y < max_pos then
                  max_pos = y
                  print(string.format("Found better y pos: %f", max_pos))
               end
            end
         end
         runtime.loadState(BRUTEFORCER_SAVESTATE)
         state_rcj = next_state
      else
         return
      end
   elseif state_rcj == "try_holding_dirs" then
      return
   end
end
