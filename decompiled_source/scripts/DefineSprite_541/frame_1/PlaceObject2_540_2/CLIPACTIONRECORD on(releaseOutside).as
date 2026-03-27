on(releaseOutside){
   this._x = Math.max(-48,Math.min(48,this._parent._xmouse));
   _root.App_VolumeSliderReleased((this._x + 48) / 96 * 99);
   this.onEnterFrame = null;
   this.gfx.gotoAndStop(1);
}
