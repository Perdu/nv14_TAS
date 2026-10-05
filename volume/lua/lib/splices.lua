-- AI-generated

local function trim(s)
   return s:match("^%s*(.-)%s*$")
end


local function unquote(s)
   s = trim(s)

   if s:sub(1, 1) == '"' and s:sub(-1) == '"' then
      return s:sub(2, -2)
   end

   return s
end


local function splice_interaction_marker(require_interaction)
   if not require_interaction then
      return nil
   end

   -- ["testdoor:1"] -> S1
   local testdoor = require_interaction:match('testdoor:(%d+)')
   if testdoor then
      return "S" .. testdoor
   end

   -- ["switch"] -> E
   if require_interaction:match('"switch"') then
      return "E"
   end

   return nil
end


local function splice_direction(objective)
   -- Position objectives use a single arrow; velocity uses a double arrow.
   local arrows = {
      ["min-x"] = "<", ["max-x"] = ">",
      ["min-y"] = "^", ["max-y"] = "v",
      ["min-vx"] = "<<", ["max-vx"] = ">>",
      ["min-vy"] = "^^", ["max-vy"] = "vv"
   }

   return arrows[objective]
end


function read_splice_files()
   splice_regions = {}
   print("reading splices file")

   local level_path = splice_files_path .. "/" .. level

   -- Standard Lua has no directory-listing API, so use find to enumerate
   -- the splice files in this level directory.
   local files = io.popen(
      'find "' .. level_path .. '" -maxdepth 1 -type f \\( -name "*.txt" -o -name "*.toml" \\) -print 2>/dev/null'
   )

   if files == nil then
      return
   end

   for filename in files:lines() do
      local file = io.open(filename, "r")

      if file then
         local config = {}

         for line in file:lines() do
            -- Ignore full-line comments.
            if not line:match("^%s*#") then
               local key, value = line:match(
                  "^%s*([%w_-]+)%s*=%s*(.-)%s*$"
               )

               if key and value then
                  -- Treat foo-bar and foo_bar identically.
                  key = key:gsub("-", "_")
                  config[key] = unquote(value)
               end
            end
         end

         file:close()

         -- Keep the filename for the label even if target_frame differs.
         local splice_name = filename:match("([^/]+)%.%w+$")
            or filename:match("([^/]+)$")
         local splice_frame = tonumber(config.target_frame) or tonumber(splice_name)

         print("Found splice file ", splice_name)

         -- Only files with a target_region have drawable rectangles.
         if config.target_region then
            local x1, x2, y1, y2 = config.target_region:match(
               "^%s*([%-%d%.]+)%s*:%s*([%-%d%.]+)%s*,%s*" ..
               "([%-%d%.]+)%s*:%s*([%-%d%.]+)%s*$"
            )

            x1 = tonumber(x1)
            x2 = tonumber(x2)
            y1 = tonumber(y1)
            y2 = tonumber(y2)

            if x1 and x2 and y1 and y2 then
               -- Missing search means window search.
               local search = (config.search == "population") and "population" or "windows"

               -- Population earliest-arrival uses secondary_objective.
               -- Window searches commonly use objective directly.
               local direction_objective = config.secondary_objective

               if not direction_objective and search ~= "population" then
                  direction_objective = config.objective
               end

               local region = {
                  name = splice_name,
                  x1 = x1,
                  x2 = x2,
                  y1 = y1,
                  y2 = y2,
                  search = search,
                  direction = splice_direction(direction_objective),
                  interaction = splice_interaction_marker(config.require_interaction)
               }

               -- Preserve numeric frame keys where possible, so a newly
               -- created splice won't be reinserted by the existing S handler.
               -- Distinct files sharing a target frame are kept separately.
               local key = splice_frame or filename
               if splice_regions[key] ~= nil then
                  key = filename
               end
               splice_regions[key] = region
            end
         end
      end
   end

   files:close()
end

function display_splices()
   for splice_key, region in pairs(splice_regions) do
      -- Backward-compatible with newly created regions that still use "P"/"W".
      local population = region.search == "population" or region.search == "P"
      local color = population and rgb(255, 0, 0) or rgb(0, 0, 255)

      gui.rectangle(
         region.x1,
         region.y1,
         region.x2 - region.x1,
         region.y2 - region.y1,
         1,
         color
      )

      -- Display the source filename without its .txt / .toml extension.
      -- The fallback also handles regions inserted by the existing S handler.
      gui.text(
         region.x1 + 1,
         region.y1 - 12,
         region.name or tostring(splice_key),
         color,
         0, 0, 12
      )

      -- Direction arrow on the corresponding side of the rectangle.
      if region.direction then
         local direction = region.direction
         local middle_x = (region.x1 + region.x2) / 2
         local middle_y = (region.y1 + region.y2) / 2
         local text_x
         local text_y

         if direction == "<" or direction == "<<" then
            text_x = region.x1 + 2
            text_y = middle_y - 6

         elseif direction == ">" or direction == ">>" then
            text_x = region.x2 - (direction == ">>" and 16 or 8)
            text_y = middle_y - 6

         elseif direction == "^" then
            text_x = middle_x - 4
            text_y = region.y1 + 1

         elseif direction == "v" then
            text_x = middle_x - 4
            text_y = region.y2 - 12

         elseif direction == "^^" then
            -- Stack vertical speed arrows rather than writing "^^" side by side.
            text_x = middle_x - 4
            gui.text(text_x, region.y1 + 1, "^", color, 0, 0, 12)
            gui.text(text_x, region.y1 + 11, "^", color, 0, 0, 12)

         elseif direction == "vv" then
            text_x = middle_x - 4
            gui.text(text_x, region.y2 - 22, "v", color, 0, 0, 12)
            gui.text(text_x, region.y2 - 12, "v", color, 0, 0, 12)
         end

         -- Horizontal arrows and single vertical position arrows.
         if text_x and text_y then
            gui.text(text_x, text_y, direction, color, 0, 0, 12)
         end
      end

      -- Required interaction in the upper-right corner: S1, S2, ... or E.
      if region.interaction then
         local text_width = #region.interaction * 7

         gui.text(
            region.x2 - text_width - 2,
            region.y1 + 1,
            region.interaction,
            color,
            0, 0, 12
         )
      end
   end

   if clean_splices_region_markers then
      splice_regions = {}
   end
end


local splice_modes = {
   s = {},

   r = {objective = "max-x",  arrow = ">"},
   R = {objective = "max-vx", arrow = ">>"},

   l = {objective = "min-x",  arrow = "<"},
   L = {objective = "min-vx", arrow = "<<"},

   u = {objective = "min-y",  arrow = "^"},
   U = {objective = "min-vy", arrow = "^^"},

   d = {objective = "max-y",  arrow = "v"},
   D = {objective = "max-vy", arrow = "vv"}
}


local function find_previous_splice(current_frame)
   local previous = 0

   for key, region in pairs(splice_regions) do
      -- Support both frame-number and filename-based table keys.
      local frame = region.frame or tonumber(key)

      if frame and frame < current_frame and frame > previous then
         previous = frame
      end
   end

   return previous
end


function create_splice_file(key)
   local mode = splice_modes[key]
   assert(mode, "Unknown splice key: " .. tostring(key))

   local f_ig = movie.currentFrame() - space_frame
   local level_path = splice_files_path .. "/" .. level
   os.execute('mkdir -p "' .. level_path .. '"')

   local filename = level_path .. "/" .. tostring(f_ig) .. ".txt"
   local file = io.open(filename, "r")

   local x, y = get_player_position()
   local x_int = math.floor(x + 0.5)
   local y_int = math.floor(y + 0.5)

   local x1 = x_int - splice_region_size_big
   local x2 = x_int + splice_region_size_big
   local y1 = y_int - splice_region_size_big
   local y2 = y_int + splice_region_size_big

   if key == 'r' or key == 'R' or key == 'l' or key == 'L' then
      x1 = x_int - splice_region_size_small
      x2 = x_int + splice_region_size_small
   elseif key == 'u' or key == 'U' or key == 'd' or key == 'D' then
      y1 = y_int - splice_region_size_small
      y2 = y_int + splice_region_size_small
   end


   local previous_frame = find_previous_splice(f_ig)

   local target_prev = math.max(
      0,
      previous_frame - splice_prev_range_prior_frames
   )

   -- Uncomment and set the secondary objective according to the key.
   local secondary_objective = "# secondary_objective = \"max-vx\""

   if mode.objective then
      secondary_objective = string.format(
         'secondary_objective = "%s"',
         mode.objective
      )
   end

   local simulate_enemies = "false"
   if input.getKey(KEY_e) ~= 0 then
      simulate_enemies = "true"
      input.setKey(KEY_e, 0)
   end


   if file == nil then
      file = assert(io.open(filename, "w"))

      file:write(string.format([[
[local]
search = "population"
target_frame = %d
range = "%d:%d"
target_region = "%d:%d,%d:%d"
simulate-enemies = %s
objective = "earliest-arrival"
%s
# require-interaction = ["testdoor:0"]
]],
         f_ig,
         target_prev, f_ig,
         x1, x2, y1, y2,
         simulate_enemies,
         secondary_objective
      ))

      print("Created splice file ", f_ig)
   end

   file:close()
   -- It would be better to run the container with a regular user (if
   -- possible for libTAS) but for now we use this easy solution
   os.execute('chown 1000:1000 -- "' .. level_path .. "/" .. tostring(f_ig) .. ".txt" .. '"')

   if f_ig > prev_splice then
      prev_splice = f_ig
   end

   if splice_regions[f_ig] == nil then
      splice_regions[f_ig] = {
         name = tostring(f_ig),
         x1 = x1,
         x2 = x2,
         y1 = y1,
         y2 = y2,
         search = "population",
         direction = mode.arrow,
         interaction = nil
      }
   end
end

