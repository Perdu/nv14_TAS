function compare_positions(compare, display_x, display_y)
   if float_eq(compare.x, x, 1e-5) then
      sign = "="
   elseif compare.x > x then
      sign = "<"
   else
      sign = ">"
   end
   gui.text(display_x, display_y, sign, 0xffffffff, 0, 0, 15)
   if float_eq(compare.y, y, 1e-5) then
      sign = "="
   elseif compare.y > y then
      sign = "^"
   else
      sign = "v"
   end
   gui.text(display_x + 10, display_y, sign, 0xffffffff, 0, 0, 15)
end
