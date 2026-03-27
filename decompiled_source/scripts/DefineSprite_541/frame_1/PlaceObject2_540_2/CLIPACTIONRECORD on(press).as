on(press){
   this.gfx.gotoAndStop(2);
   this.onEnterFrame = function()
   {
      this._x = Math.max(-48,Math.min(48,this._parent._xmouse));
      _root.App_VolumeSliderMoved((this._x + 48) / 96 * 99);
   };
}
