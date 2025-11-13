level = "04-3"
memy=""
local levels = dofile("/home/lua/levels.lua")

function onPaint()
   local y_num = tonumber(memy, 16)
   local y = memory.readd(y_num)
   local x_num = y_num - 56
   local x = memory.readd(x_num)
   gui.ellipse(x, y, 10, 10)
   gui.text(150, 580, string.format("%f ; %f", x, y))

   -- door
   gui.ellipse(levels[level].door_x, levels[level].door_y, 12, 12)
end

function onFrame()
   local f = movie.currentFrame()
   if f == 47 then
      print(levels[level].n_y)
      local i = ramsearch.newsearch(9, 0, 1, levels[level].n_y, "==")
      print(string.format("nb_results newsearch: %d", i))
   end
   if f == 48 then
      -- ramsearch.set_comparison_operator("")
      local i = ramsearch.search()
      print(string.format("nb_results: %d", i))
      -- local v = ramsearch.get_current_value(0)
      -- print(string.format("current value: %f", v))
      for j = 0,i-1,1
      do
         local v = ramsearch.get_current_value(j)
         -- print(string.format("current value: %f", v))
      end
   end
   if f == 49 then
      local i = ramsearch.search(0, 0, "!=")
      print(string.format("nb_results: %d", i))
      if i == 1 then
         memy = ramsearch.get_address(j)
      else
         print("Error: found too many values")
         for j = 0,i-1,1
         do
            local v = ramsearch.get_current_value(j)
            local addr = ramsearch.get_address(j)
            print(string.format("current value: %f @ %s", v, addr))
         end
      end
   end
end
