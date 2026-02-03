-- https://discord.com/channels/197765375503368192/199460839252688896/1437946735665352714
HITBOX_PLAYER = 10
HITBOX_EXIT = 12
HITBOX_EXIT_SWITCH = 6
HITBOX_SWITCH = 5
HITBOX_DRONE = 9
HITBOX_MINE = 4
HITBOX_GOLD = 6


function draw_hitboxes()
      local data = levels[level]
      if not data then return end

      for _, e in ipairs(data.doors) do
         gui.ellipse(e.x, e.y, HITBOX_EXIT, HITBOX_EXIT, 1)
         gui.ellipse(e.sx, e.sy, HITBOX_EXIT_SWITCH, HITBOX_EXIT_SWITCH, 1)
      end

      drawList(data.mines, HITBOX_MINE, 255, 0, 0)         -- red mines
      -- drawList(data.drones, 9, 0, 0, 255)
      -- drawList(data.floorguards, 6, 0, 0, 0)
      if draw_gold_hitboxes then
         drawList(data.gold, HITBOX_GOLD, 255, 255, 0)
      end
      -- drawList(data.launchpads, 6, 255, 0, 255) -- magenta launchpads
      drawList(data.switches, HITBOX_SWITCH, 0, 255, 255)    -- cyan switches
end

function display_distance_to_doors(x, y, doors)
   for _, sw in ipairs(doors) do
      local dx = x - sw.x
      local dy = y - sw.y

      -- distance between the centers
      local center_dist = math.sqrt(dx*dx + dy*dy)

      -- subtract radii (player=10, door=12)
      local edge_dist = center_dist - (10 + 12)

      if edge_dist > 0 and edge_dist < 50 then
         -- draw the value on screen
         local location
         if sw.y < y then
            location = sw.y - 28
         else
            location = sw.y + 10
         end
         gui.text(sw.x - 15, location, string.format("%.2f", edge_dist), 0xffffff00)
      end

      -- doorswitches
      dx = x - sw.sx
      dy = y - sw.sy

      -- distance between centers
      center_dist = math.sqrt(dx*dx + dy*dy)

      -- player radius = 10, doorswitch radius = 6
      edge_dist = center_dist - (10 + 6)

      if edge_dist > 0 and edge_dist < 50 then
         local location
         if sw.sy < y then
            location = sw.sy - 20
         else
            location = sw.sy + 10
         end
         -- draw the value near the switch
         gui.text(sw.sx - 15, location, string.format("%.2f", edge_dist), 0xff0000ff)  -- blue
      end

   end
end

function display_distance_to_switches(x, y, switches)
    for _, sw in ipairs(switches) do
        local dx = x - sw.x
        local dy = y - sw.y

        -- distance between centers
        local center_dist = math.sqrt(dx*dx + dy*dy)

        -- player radius = 10, switch radius = 5
        local edge_dist = center_dist - (10 + 5)

        if edge_dist > 0 and edge_dist < 50 then
            -- draw the value near the switch
           local location
           if sw.y < y then
              location = sw.y - 18
           else
              location = sw.y + 10
           end
            gui.text(sw.x - 15, location, string.format("%.2f", edge_dist), 0xff0000ff)  -- blue
        end
    end
end
