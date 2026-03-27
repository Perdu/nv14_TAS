this.onRollOver = function()
{
   this.gfx.gotoAndStop(2);
};
this.onRollOut = function()
{
   this.gfx.gotoAndStop(1);
};
this.onReleaseOutside = function()
{
   this.gfx.gotoAndStop(1);
};
this.onRelease = function()
{
   this.gfx.gotoAndStop(2);
};
this.onPress = function()
{
   this.gfx.gotoAndStop(3);
   _root.App_Custom_SortButtonPressed(2);
};
