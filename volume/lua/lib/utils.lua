function get_player_position()
   if memy ~= "" then
      local y_num = tonumber(memy, 16)
      y = memory.readd(y_num)
      local x_num = y_num - 56
      x = memory.readd(x_num)
      return x, y
   else
      return nil
   end
end

function get_player_speed()
   if memspeed_y ~= "" then
      local y_num = tonumber(memspeed_y, 16)
      local vy = memory.readd(y_num)
      local x_num = y_num - 56
      local vx = memory.readd(x_num)
      return vx, vy
   else
      return nil
   end
end

function float_eq(a, b, tol)
    tol = tol or 1e-5  -- default tolerance
    return math.abs(a - b) < tol
end

-- Convert r,g,b to 0xAARRGGBB color
function rgb(r,g,b,a)
    a = a or 255
    return (a << 24) | (r << 16) | (g << 8) | b
end

function drawList(list, size, r, g, b)
   -- print(list)
   for _, e in ipairs(list) do
      gui.ellipse(e.x, e.y, size, size, 1, rgb(r, g, b))
   end
end

-- Insert or update path at a specific frame
local function recordFrame(frame, x, y, vx, vy)
    if not path[frame] then
        table.insert(knownFrames, frame)
        table.sort(knownFrames)
    end
    path[frame] = {x = x, y = y, vx = vx, vy = vy}
end
