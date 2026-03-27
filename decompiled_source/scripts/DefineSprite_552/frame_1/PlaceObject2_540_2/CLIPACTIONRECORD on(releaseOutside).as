on(releaseOutside){
   this._x = Math.max(-48,Math.min(48,this._parent._xmouse));
   _root.App_SpeedSliderMoved((this._x + 48) / 96,true);
   this.onEnterFrame = null;
   this.gfx.gotoAndStop(1);
}
