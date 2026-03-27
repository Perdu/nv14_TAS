function ConsoleObject(x, y, w, h)
{
   this.CONSOLE_KEY = 109;
   this.CONSOLE_KEY_WAS_DOWN = false;
   this.UP_KEY = 105;
   this.DN_KEY = 99;
   this.SCROLL_WAS_DOWN = false;
   this.SCROLLSPEED = 4;
   this.SCROLLCOUNTER = 0;
   this.numLines = 16;
   this.maxLen = 80;
   this.tabs = 0;
   this.buffer = new Array();
   this.buffer.push("\n====[N]====");
   this.txt = "";
   this.topLine = 0;
   this.botLine = 0;
   this.pos = new Vector2(44,28);
   this.dimensions = new Vector2(w,h);
   this.curpos = new Vector2(x,y);
   var _loc4_ = gfx.GetNextDepth_Front();
   var _loc3_ = gfx.CreateEmptySprite(LAYER_CONSOLE);
   _loc3_.createTextField("consoleTxtField",990,this.pos.x,this.pos.y,w,h);
   this.mc = _loc3_.consoleTxtField;
   this.mc.multiline = true;
   this.mc.wordWrap = true;
   this.mc.selectable = false;
   this.mc.embedFonts = true;
   var _loc2_ = new TextFormat();
   _loc2_.color = 0;
   _loc2_.font = "n_uni05_53";
   _loc2_.size = 8;
   _loc2_.align = "left";
   this.mc.setNewTextFormat(_loc2_);
   this.mc.setTextFormat(_loc2_);
   this.active = true;
}
ConsoleObject.prototype.AnimateIn = function()
{
   var _loc2_ = this.pos.x - this.curpos.y;
   if(Math.abs(_loc2_) < 20)
   {
      this.curpos.y = this.pos.y;
      this.Animate = null;
   }
   else
   {
      this.curpos.y += _loc2_ * 0.15;
   }
   this.mc._y = this.curpos.y;
};
ConsoleObject.prototype.AnimateOut = function()
{
   var _loc2_ = - this.dimensions.y - this.curpos.y;
   if(Math.abs(_loc2_) < 20)
   {
      this.curpos.y = - this.dimensions.y;
      this.Animate = null;
      this.mc._visible = false;
   }
   else
   {
      this.curpos.y += _loc2_ * 0.15;
   }
   this.mc._y = this.curpos.y;
};
ConsoleObject.prototype.Update = function()
{
   this.Animate();
   if(Key.isDown(this.CONSOLE_KEY))
   {
      if(!this.CONSOLE_KEY_WAS_DOWN)
      {
         this.CONSOLE_KEY_WAS_DOWN = true;
         this.Toggle();
      }
   }
   else
   {
      this.CONSOLE_KEY_WAS_DOWN = false;
   }
   var _loc2_;
   if(this.active)
   {
      _loc2_ = 0;
      if(Key.isDown(this.UP_KEY))
      {
         _loc2_ -= 1;
      }
      else if(Key.isDown(this.DN_KEY))
      {
         _loc2_ += 1;
      }
      else
      {
         this.SCROLL_WAS_DOWN = false;
      }
      if(_loc2_ != 0)
      {
         if(!this.SCROLL_WAS_DOWN)
         {
            this.SCROLL_WAS_DOWN = true;
            this.SCROLLCOUNTER = 0;
            this.topline = Math.max(0,Math.min(this.buffer.length - this.numLines,this.topline + _loc2_));
         }
         else if(this.SCROLLSPEED < this.SCROLLCOUNTER++)
         {
            this.SCROLL_WAS_DOWN = false;
         }
      }
      this.Refresh();
   }
};
ConsoleObject.prototype.Show = function()
{
   this.mc._visible = true;
   this.active = true;
   this.Animate = this.AnimateIn;
};
ConsoleObject.prototype.Hide = function()
{
   this.active = false;
   this.Animate = this.AnimateOut;
};
ConsoleObject.prototype.Toggle = function()
{
   if(this.active)
   {
      this.Hide();
   }
   else
   {
      this.Show();
   }
};
ConsoleObject.prototype.Refresh = function()
{
   this.txt = "";
   var _loc2_ = this.topLine;
   while(_loc2_ < this.buffer.length)
   {
      this.txt += this.buffer[_loc2_];
      _loc2_ = _loc2_ + 1;
   }
   this.mc.text = this.txt;
};
ConsoleObject.prototype.Clear = function()
{
   delete this.buffer;
   this.buffer = new Array();
   this.txt = "====[N]====";
   this.mc.text = this.txt;
   this.tabs = 0;
   this.curLine = 0;
};
ConsoleObject.prototype.AddLine = function(str)
{
   var _loc2_ = 0;
   while(_loc2_ < this.tabs)
   {
      str = "\t" + str;
      _loc2_ = _loc2_ + 1;
   }
   str = "\n" + str;
   this.botLine = this.botLine + 1;
   this.topLine = Math.max(this.topLine,this.botLine - this.numLines);
   this.buffer.pop();
   this.buffer.push(str);
   this.buffer.push("\n====[N]====");
};
ConsoleObject.prototype.Append = function(str)
{
   if(this.maxLen - this.tabs * 4 < this.buffer[this.buffer.length - 2].length + str.length)
   {
      this.AddLine(str);
   }
   else
   {
      this.buffer[this.buffer.length - 2] += str;
   }
};
ConsoleObject.prototype.StartTab = function()
{
};
ConsoleObject.prototype.StopTab = function()
{
};
