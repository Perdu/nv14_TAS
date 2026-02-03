function display_drones_number()
   local player_x, player_y = get_player_position()
   local screen_w, screen_h = 792, 600
   for i = 1, #drones_memx do
      local x = memory.readd(drones_memx[i])
      local y = memory.readd(drones_memx[i] + 56)
      if x and y then
         -- gui.ellipse(x, y, 6, 6, 1, 0xffff0000)
         gui.text(x - 4, y - 8, string.format("%d", i))
      end
      x_target = memory.readd(drones_target_memx[i])
      y_target = memory.readd(drones_target_memx[i] + 56)
      if display_drones_targets and x_target and y_target then
         gui.ellipse(x_target, y_target, HITBOX_DRONE, HITBOX_DRONE, 1, 0xffff0000)
         gui.text(x_target - 4, y_target - 8, string.format("%d", i), 0xff0000ff)
      end
      if display_drones_raycasts and player_x and player_y then
         -- print(string.format("D%d: %f, %f", i, math.abs(x - x_target), math.abs(y - y_target)))
         if math.abs(x - x_target) < 2 and math.abs(y - y_target) < 2 then
            -- print(string.format("Drone %d is detecting", i))
            local x_dist_to_player = math.abs(player_x - x) - HITBOX_PLAYER
            local y_dist_to_player = math.abs(player_y - y) - HITBOX_PLAYER

            if x_dist_to_player < MAX_DIST_RAYCAST_DISPLAY then
               if x_dist_to_player < 0 then
                  color = 0xffff0000
               else
                  color = 0xff0000ff
                  -- display distance at opposite side of the line
                  local x_dist_to_player_signed = player_x - x
                  local x_offset = (x_dist_to_player_signed > 0) and -x_dist_to_player_signed - HITBOX_PLAYER or -x_dist_to_player_signed + HITBOX_PLAYER
                  local text_x = x + x_offset
                  gui.text(text_x, player_y, string.format("%.2f", x_dist_to_player), 0xff0000ff)
               end
               if player_y < y then
                  gui.line(x, 0, x, y, color)   -- up
               elseif player_y > y then
                  gui.line(x, y, x, screen_h, color) -- down
               end
            end
            if y_dist_to_player < MAX_DIST_RAYCAST_DISPLAY then
               if y_dist_to_player < 0 then
                  color = 0xffff0000
               else
                  color = 0xff0000ff
                  -- display distance at opposite side of the line
                  local y_dist_to_player_signed = player_y - y
                  local y_offset = (y_dist_to_player_signed > 0) and -y_dist_to_player_signed - HITBOX_PLAYER or -y_dist_to_player_signed + HITBOX_PLAYER
                  local text_y = y + y_offset
                  gui.text(player_x, text_y, string.format("%.2f", y_dist_to_player), 0xff0000ff)
               end
               if player_x < x then
                  gui.line(0, y, x, y, color)   -- left
               elseif player_x > x then
                  gui.line(x, y, screen_w, y, color) -- right
               end
            end
            -- gui.line(x, 0, x, 600, 0xff0000ff)
            -- gui.line(0, y, 792, y, 0xff0000ff)
         end
      end
   end
end
