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
         if f == space_frame + 2 then
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
            -- local i = ramsearch.search(0, 0, "!=")
            -- if dbg then
            --    print(string.format("nb_results search speed 3: %d", i))
            -- end
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

if search_for_drones_position and ramsearch_done and not ramsearch_drones_done then
   local f = movie.currentFrame()

   if f == space_frame + 1 then
      drones_candidates = {}
      print("Searching for drones position...")

      for drone_i = 1, #levels[level].drones do
         drones_candidates[drone_i] = {}
         local target = levels[level].drones[drone_i]

         local i = ramsearch.newsearch(9, 0, 1, target.x, "==")

         local nb_stored = 0
         for j = 0, i - 1 do
            local addr_x = tonumber(ramsearch.get_address(j), 16)
            local addr_y = addr_x + 56

            local y = memory.readd(addr_y)
            -- print(string.format("%f %f", y, target.y))
            if y == target.y then
               table.insert(drones_candidates[drone_i], {
                               x_addr = addr_x,
                               y_addr = addr_y
               })
               nb_stored = nb_stored + 1
            end
         end
         print(string.format("Drone %d: %d candidates", drone_i, nb_stored))
      end

   elseif f == space_frame + 4 then

      for drone_i, candidates in pairs(drones_candidates) do
         local target = levels[level].drones[drone_i]

         for _, c in ipairs(candidates) do
            local x = memory.readd(c.x_addr)
            local y = memory.readd(c.y_addr)

            -- compare against known initial values
            if (math.abs(x - target.x) > 0 and math.abs(x - target.x) < 4)
               or (math.abs(y - target.y) > 0 and math.abs(y - target.y) < 4)
            then
               drones_memx[drone_i] = c.x_addr
               print(string.format("Confirmed drone %d @ %s",
                                   drone_i, c.x_addr))
            elseif (math.abs(x - target.x) > 0)
               or (math.abs(y - target.y) > 0)
            then
               drones_target_memx[drone_i] = c.x_addr
               print(string.format("Confirmed drone %d target", drone_i))
               if remove_drone == drone_i then
                  memory.writed(c.x_addr, 0)
               end
            end
         end
         ramsearch_drones_done = true

      end
   end
end
