this.onRelease = function()
{
   _root.App_FocusKeyConfig(this);
};
this.onRollOver = function()
{
   this.gfx.gotoAndStop(2);
};
this.onRollOut = function()
{
   this.gfx.gotoAndStop(1);
};
this.onKeyDown = function()
{
   var _loc3_ = Key.getCode();
   _root.App_SubmitKeyConfig(this,"pause",_loc3_);
};
this.onKeyUp = function()
{
};
