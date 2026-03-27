on(releaseOutside){
   this._x = Math.max(-128,Math.min(128,this._parent._xmouse));
   _root.App_ColSliderReleased();
   this.onEnterFrame = null;
   this.gfx.gotoAndStop(1);
}
