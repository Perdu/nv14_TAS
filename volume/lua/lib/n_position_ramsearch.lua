-- If Space was pressed, save and pause
if triggered then
   space_frame = movie.currentFrame()
   runtime.saveState(SAVE_SLOT)
   if dbg then
      print(string.format("Looking for player at y position %f", levels[level].n_y))
   end
   if math.floor(levels[level].n_y) == levels[level].n_y then
      -- it's round, we can look for the exact value (majority case)
      local i = ramsearch.newsearch(9, 0, 1, levels[level].n_y, "==")
      if dbg then
         print(string.format("nb_results newsearch (==): %d", i))
      end
   else
      local i = ramsearch.newsearch(9, 0, 1, levels[level].n_y - 0.1, ">")
      if dbg then
         print(string.format("nb_results newsearch (>): %d", i))
      end
      i = ramsearch.search(1, levels[level].n_y + 0.1, "<")
      if dbg then
         print(string.format("nb_results search (<): %d", i))
      end
   end

   -- Disable for this session only
   done = true
   triggered = false
end

if not ramsearch_done then
   local f = movie.currentFrame()
   if not pos_found then
      if grounded_levels[level] then
         if f == space_frame + 3 then
            -- as we added a jump, we should be 3 pixels higher than start
            local i = ramsearch.search(1, levels[level].n_y - 3, "==")
            if dbg then
               print(string.format("nb_results: %d", i))
            end
            if i == 1 then
               memy = ramsearch.get_address(0)
               pos_found = true
               print(string.format("memy: %s", memy))
            end
            runtime.loadState(SAVE_SLOT)
         end
      else
         if f == space_frame + 1 then
            local i = ramsearch.search()
            if dbg then
               print(string.format("nb_results: %d", i))
            end
         elseif f == space_frame + 2 then
            local i = ramsearch.search(0, 0, "!=")
            if dbg then
               print(string.format("nb_results: %d", i))
            end
            if i == 1 then
               memy = ramsearch.get_address(0)
               pos_found = true
               print(string.format("memy: %s", memy))
            else
               -- try filtering a bit more
               print("Too many results, we try filtering a bit more")
               local i = ramsearch.search(1, levels[level].n_y + 5.0, "<")
               if dbg then
                  print(string.format("nb_results: %d", i))
               end
               local i = ramsearch.search(1, levels[level].n_y - 5.0, ">")
               if dbg then
                  print(string.format("nb_results: %d", i))
               end
               if i == 1 then
                  memy = ramsearch.get_address(0)
                  pos_found = true
                  print(string.format("memy: %s", memy))
               else
                  print(string.format("Error: found too many values (%d). Checking if any of them has x position at the right place.", i))
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
      end
   end
   -- And now, speed
   if grounded_levels[level] then
      if pos_found then
         if f == space_frame + 3 then
            i = ramsearch.newsearch(9, 0, 1, -0.14, "<")
            if dbg then
               print(string.format("nb_results newsearch speed: %d", i))
            end
            i = ramsearch.search(1, -0.16, ">")
            if dbg then
               print(string.format("nb_results search speed 2: %d", i))
            end
         elseif f == space_frame + 4 then
            local i = ramsearch.search(1, -0.29, "<")
            if dbg then
               print(string.format("nb_results search speed 3: %d", i))
            end
            i = ramsearch.search(1, -0.30, ">")
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
   else
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
end
