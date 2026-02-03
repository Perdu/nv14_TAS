function get_speed_color(vx, vy)
    local horizontal_color = 0xffff5500
    local vertical_color = 0xff0000ff
    if vy >= 7.00 or vy <= -7.00 then
       vertical_color = 0xffff2200
    end
    return horizontal_color, vertical_color
end

function draw_velocity_arrows(x, y, vx, vy)
    local horizontal_color, vertical_color = get_speed_color(vx, vy)
    -- scale speed so arrows stay readable
    local scale = 4     -- adjust if arrows feel too long/short

    -- horizontal arrow
    local hx = x + vx * scale
    gui.line(x, y, hx, y, horizontal_color)

    -- small arrowhead for horizontal
    if vx ~= 0 then
        local dir = (vx > 0) and 1 or -1
        gui.line(hx, y, hx - 4 * dir, y - 3, horizontal_color)
        gui.line(hx, y, hx - 4 * dir, y + 3, horizontal_color)
    end

    -- vertical arrow
    local vy_scaled = vy * scale
    local hy = y + vy_scaled
    gui.line(x, y, x, hy, vertical_color)
    if vy >= 7.00 or vy <= -7.00 then
       gui.line(x - 1, y, x - 1, hy, vertical_color)
       gui.line(x + 1, y, x + 1, hy, vertical_color)
    end

    -- arrowhead for vertical
    if vy ~= 0 then
        local dir = (vy > 0) and 1 or -1
        gui.line(x, hy, x - 3, hy - 4 * dir, vertical_color)
        gui.line(x, hy, x + 3, hy - 4 * dir, vertical_color)
    end

    -- compute endpoint of combined vector
    local rx = x + vx * scale
    local ry = y + vy * scale

    -- choose a color for the resultant vector
    local result_color = 0xffffff00  -- orange

    -- draw line for combined vector
    gui.line(x, y, rx, ry, result_color)

    -- draw a proper arrowhead
    if vx ~= 0 or vy ~= 0 then
       -- normalize direction vector
       local len = math.sqrt(vx*vx + vy*vy)
       local dir_x = (vx / len)
       local dir_y = (vy / len)

       local arrow_size = 5  -- pixels
       local perp_x = -dir_y
       local perp_y = dir_x

       -- two lines forming the arrowhead
       gui.line(rx, ry,
                rx - dir_x*arrow_size + perp_x*arrow_size/2,
                ry - dir_y*arrow_size + perp_y*arrow_size/2,
                result_color)
       gui.line(rx, ry,
                rx - dir_x*arrow_size - perp_x*arrow_size/2,
                ry - dir_y*arrow_size - perp_y*arrow_size/2,
                result_color)
    end

end
