this.onRollOver = function()
{
   this.gfx.gotoAndStop(2);
};
this.onRollOut = function()
{
   this.onEnterFrame = null;
   this.gfx.gotoAndStop(1);
};
this.onReleaseOutside = function()
{
   this.onEnterFrame = null;
   this.gfx.gotoAndStop(1);
};
this.onRelease = function()
{
   this.onEnterFrame = null;
   this.gfx.gotoAndStop(2);
};
this.onPress = function()
{
   this.gfx.gotoAndStop(3);
   _root.App_Custom_ScrollButtonPressed(1);
   this.delay = 30;
   this.onEnterFrame = function()
   {
      this.delay = this.delay - 1;
      if(this.delay < 0)
      {
         this.delay = 0;
         _root.App_Custom_ScrollButtonPressed(1);
      }
   };
   this.onMouseUp = function()
   {
      this.onEnterFrame = null;
   };
};
