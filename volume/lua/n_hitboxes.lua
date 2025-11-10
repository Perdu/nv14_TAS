level = "02-0"
memy="55f7270eb778"
local levels = dofile("lua/levels.lua")

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
