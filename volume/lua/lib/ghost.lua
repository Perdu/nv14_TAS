local function loadGhost()
    local file = io.open(ghostFilePath, "r")
    if not file then
        print("ERROR: Could not open ghost CSV file!")
        return
    end

    for line in file:lines() do
        local frame, x, y, shift, left, right, vx, vy = line:match("(%d+),([^,]+),([^,]+),([^,]+),([^,]+),([^,]+),([^,]+),([^,]+)")
        if frame and x and y then
           ghostData[tonumber(frame)] = {
              x = tonumber(x),
              y = tonumber(y),
              shift = tonumber(shift),
              left = tonumber(left),
              right = tonumber(right),
              vx = tonumber(vx),
              vy = tonumber(vy)
           }
        end
    end

    file:close()
    print("Ghost loaded: " .. tostring(#ghostData) .. " frames")
end

function display_ghost_history(ghost, f)
   -- vertical offset for listing
   local baseY = 150
   local lineH = 14
   local rel = f - space_frame
   local fontsize = 14
   local ghost_hist_x = 771
   -- ---- PREVIOUS 10 FRAMES ----
   for i = 10, 1, -1 do
      local gf = ghostData[rel - i]
      if gf then
         local y = baseY + (10 - i) * lineH
         color = (gf.shift == 1) and 0xff8888ff or 0xff000000
         gui.text(ghost_hist_x, y, "J", color, 0, 0, fontsize)

         color = (gf.left == 1) and 0xff8888ff or 0xff000000
         gui.text(ghost_hist_x + 8, y, "<", color, 0, 0, fontsize)

         color = (gf.right == 1) and 0xff8888ff or 0xff000000
         gui.text(ghost_hist_x + 15, y, ">", color, 0, 0, fontsize)
      end
   end
   -- ---- CURRENT FRAME ----
   local gf = ghostData[rel]
   if gf then
      local y = baseY + 11 * lineH
      color = (gf.shift == 1) and 0xffffffff or 0xff000000
      gui.text(ghost_hist_x, y, "J", color, 0, 0, fontsize)

      color = (gf.left == 1) and 0xffffffff or 0xff000000
      gui.text(ghost_hist_x + 8, y, "<", color, 0, 0, fontsize)

      color = (gf.right == 1) and 0xffffffff or 0xff000000
      gui.text(ghost_hist_x + 15, y, ">", color, 0, 0, fontsize)
   end
   -- ---- NEXT 10 FRAMES ----
   for i = 1, 10 do
      local gf = ghostData[rel + i]
      if gf then
         local y = baseY + (11 + i + 1) * lineH
         color = (gf.shift == 1) and 0xff88ff88 or 0xff000000
         gui.text(ghost_hist_x, y, "J", color, 0, 0, fontsize)

         color = (gf.left == 1) and 0xff88ff88 or 0xff000000
         gui.text(ghost_hist_x + 8, y, "<", color, 0, 0, fontsize)

         color = (gf.right == 1) and 0xff88ff88 or 0xff000000
         gui.text(ghost_hist_x + 15, y, ">", color, 0, 0, fontsize)

         -- gui.text(600, y, str, 0xff88ff88)  -- light green for future
      end
   end
end
