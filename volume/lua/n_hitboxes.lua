memy="55f7270eb778"
x_door="36"
y_door="60"

function onPaint()
   local y_num = tonumber(memy, 16)
   local y = memory.readd(y_num)
   local x_num = y_num - 56
   local x = memory.readd(x_num)
   gui.ellipse(x, y, 10, 10)
   gui.text(150, 580, string.format("%f ; %f", x, y))

   -- door
   gui.ellipse(x_door, y_door, 13, 13)
end

