on(press){
   _root.App_Configure_SetFocusCustomColorButton();
   this.gfx.gotoAndStop(2);
   this.onEnterFrame = function()
   {
      this._x = Math.max(-128,Math.min(128,this._parent._xmouse));
      _root.App_ColSliderMoved();
   };
}
