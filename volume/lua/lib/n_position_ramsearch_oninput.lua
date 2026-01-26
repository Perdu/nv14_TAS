if not ramsearch_done and grounded_levels[level] and not original_input_modified then
   local f = movie.currentFrame()
   if f == space_frame + 1 then
      shift_pressed = input.getKey(KEY_SHIFT)
      print(string.format("Shift pressed? %d", shift_pressed))
      input.setKey(KEY_SHIFT, 1)
      original_input_modified = true
   end
elseif ramsearch_done and grounded_levels[level] and original_input_modified then
   runtime.playPause()
   if movie.currentFrame() == space_frame + 1 then
      original_input_modified = false
      runtime.loadState(SAVE_SLOT)
   end
end
