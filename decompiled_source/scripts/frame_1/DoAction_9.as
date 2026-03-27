function InputManager()
{
   this.vrend = new VectorRenderer();
   this.mPos = new Vector2(this.vrend.buffer._xmouse,this.vrend.buffer._ymouse);
   this.mOldpos = new Vector2(this.vrend.buffer._xmouse,this.vrend.buffer._ymouse);
   this.mDelta = new Vector2(0,0);
   this.mDownPos = new Vector2(0,0);
   this.mUpPos = new Vector2(0,0);
   this.onMouseDown = this.CaptureMouseDown;
   this.onMouseUp = this.CaptureMouseUp;
   Mouse.addListener(this);
   this.mState = false;
   this.mOldState = false;
   this.mPressed = false;
   this.mReleased = false;
   this.kCode = new Array();
   this.kState = new Array();
   this.kOldState = new Array();
   this.tKey = new Array();
   this.tState = new Array();
}
InputManager.prototype.RegisterKey = function(knum)
{
   var _loc2_ = this.kCode.length;
   this.kCode.push(knum);
   this.kState[_loc2_] = false;
   this.kOldState[_loc2_] = false;
   return _loc2_;
};
InputManager.prototype.RegisterToggle = function(knum)
{
   var _loc2_ = this.tKey.length;
   this.tKey.push(this.RegisterKey(knum));
   this.tState[_loc2_] = false;
   return _loc2_;
};
InputManager.prototype.Update = function()
{
   this.mOldpos.x = this.mPos.x;
   this.mOldpos.y = this.mPos.y;
   this.mPos.x = this.vrend.buffer._xmouse;
   this.mPos.y = this.vrend.buffer._ymouse;
   this.mDelta.x = this.mPos.x - this.mOldpos.x;
   this.mDelta.y = this.mPos.y - this.mOldpos.y;
   if(this.mState && !this.mOldState)
   {
      this.mPressed = true;
      this.mOldState = true;
      this.mDownPos.x = this.mPos.x;
      this.mDownPos.y = this.mPos.y;
   }
   else
   {
      this.mPressed = false;
   }
   if(!this.mState && this.mOldState)
   {
      this.mReleased = true;
      this.mOldState = false;
      this.mUpPos.x = this.mPos.x;
      this.mUpPos.y = this.mPos.y;
   }
   else
   {
      this.mReleased = false;
   }
   if(this.mState)
   {
      this.mUpPos.x = this.mPos.x;
      this.mUpPos.y = this.mPos.y;
   }
   var _loc2_ = 0;
   while(_loc2_ < this.kCode.length)
   {
      this.kOldState[_loc2_] = Key.isDown(this.kCode[_loc2_]);
      _loc2_ = _loc2_ + 1;
   }
   var _loc3_ = this.kOldState;
   this.kOldState = this.kState;
   this.kState = _loc3_;
   _loc2_ = 0;
   while(_loc2_ < this.tKey.length)
   {
      if(this.Pressed(this.tKey[_loc2_]))
      {
         this.tState[_loc2_] = !this.tState[_loc2_];
      }
      _loc2_ = _loc2_ + 1;
   }
};
InputManager.prototype.CaptureMouseDown = function()
{
   this.mOldState = false;
   this.mState = true;
};
InputManager.prototype.CaptureMouseUp = function()
{
   this.mOldState = true;
   this.mState = false;
};
InputManager.prototype.getMousePos = function()
{
   return this.mPos.clone();
};
InputManager.prototype.getMouseDelta = function()
{
   return this.mDelta.clone();
};
InputManager.prototype.getMouseDragDelta = function()
{
   return this.mUpPos.minus(this.mDownPos);
};
InputManager.prototype.getMouseDownPos = function()
{
   return this.mDownPos.clone();
};
InputManager.prototype.getMouseUpPos = function()
{
   return this.mUpPos.clone();
};
InputManager.prototype.MousePressed = function()
{
   return this.mPressed;
};
InputManager.prototype.MouseReleased = function()
{
   return this.mReleased;
};
InputManager.prototype.MouseDown = function()
{
   return this.mState;
};
InputManager.prototype.Down = function(knum)
{
   return this.kState[knum];
};
InputManager.prototype.Pressed = function(knum)
{
   return this.kState[knum] && !this.kOldState[knum];
};
InputManager.prototype.Released = function(knum)
{
   return !this.kState[knum] && this.kOldState[knum];
};
InputManager.prototype.Toggled = function(tnum)
{
   return this.tState[tnum];
};
