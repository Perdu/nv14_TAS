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
   if objective == "min-x" or objective == "min-vx" then
      return "<"
   elseif objective == "max-x" or objective == "max-vx" then
      return ">"
   elseif objective == "min-y" or objective == "min-vy" then
      return "^"
   elseif objective == "max-y" or objective == "max-vy" then
      return "v"
   end

   return nil
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

         -- Use target_frame when present, otherwise use the filename.
         local splice_frame =
            tonumber(config.target_frame) or
            tonumber(filename:match("([^/]+)%.%w+$"))

         print("Found splice file ", splice_frame)

         if config.target_region and splice_frame then
            local x1, x2, y1, y2 = config.target_region:match(
               "^%s*([%-%d%.]+)%s*:%s*([%-%d%.]+)%s*,%s*" ..
               "([%-%d%.]+)%s*:%s*([%-%d%.]+)%s*$"
            )

            x1 = tonumber(x1)
            x2 = tonumber(x2)
            y1 = tonumber(y1)
            y2 = tonumber(y2)

            if x1 and x2 and y1 and y2 then
               local search = config.search or "windows"

               local search_marker
               if search == "population" then
                  search_marker = "P"
               else
                  search_marker = "W"
               end

               -- Population earliest-arrival uses secondary_objective.
               -- Window searches commonly use objective directly.
               local direction_objective = config.secondary_objective

               if not direction_objective and search ~= "population" then
                  direction_objective = config.objective
               end

               splice_regions[splice_frame] = {
                  x1 = x1,
                  x2 = x2,
                  y1 = y1,
                  y2 = y2,
                  search = search_marker,
                  direction = splice_direction(direction_objective),
                  interaction = splice_interaction_marker(config.require_interaction)
               }
            end
         end
      end
   end

   files:close()
end

function display_splices()
   for splice_frame, region in pairs(splice_regions) do
      local color = rgb(255, 0, 0)

      local width = region.x2 - region.x1
      local height = region.y2 - region.y1

      gui.rectangle(
         region.x1,
         region.y1,
         width,
         height,
         1,
         color
      )

      -- Frame number above the rectangle.
      gui.text(
         region.x1 + 1,
         region.y1 - 12,
         tostring(splice_frame),
         color,
         0, 0, 12
      )

      -- P = population, W = window.
      gui.text(
         region.x1 + 2,
         region.y1 + 1,
         region.search,
         color,
         0, 0, 12
      )

      -- Direction arrow, placed on the corresponding side.
      if region.direction then
         local text_x
         local text_y

         if region.direction == "<" then
            text_x = region.x1 + 2
            text_y = (region.y1 + region.y2) / 2 - 6

         elseif region.direction == ">" then
            text_x = region.x2 - 8
            text_y = (region.y1 + region.y2) / 2 - 6

         elseif region.direction == "^" then
            text_x = (region.x1 + region.x2) / 2 - 4
            text_y = region.y1 + 1

         elseif region.direction == "v" then
            text_x = (region.x1 + region.x2) / 2 - 4
            text_y = region.y2 - 12
         end

         gui.text(
            text_x,
            text_y,
            region.direction,
            color,
            0, 0, 12
         )
      end

      -- Required interaction: S1, S2, ... or E.
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
