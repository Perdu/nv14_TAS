function ExitObject()
{
   this.name = "exit";
   this.pos = new Vector2(24,55);
   this.trigger = new Object();
   this.trigger.pos = new Vector2(87,39);
   this.trigger.r = tiles.xw * 0.5;
   this.isOpen = false;
   this.r = tiles.xw;
   objects.Register(this);
   this.mc = gfx.CreateSprite("debugExitMC",LAYER_WALLS);
   this.mc._visible = false;
   this.trigger.mc = gfx.CreateSprite("debugExitTriggerMC",LAYER_WALLS);
   this.trigger.mc._visible = false;
}
TREASURE_RADIUS = 4;
ExitObject.prototype.Destruct = function()
{
   gfx.DestroyMC(this.mc);
   delete this.mc;
   gfx.DestroyMC(this.trigger.mc);
   delete this.trigger.mc;
   delete this.trigger;
};
ExitObject.prototype.Init = function(params)
{
   if(params.length == 4)
   {
      this.pos.x = params[0];
      this.pos.y = params[1];
      this.trigger.pos.x = params[2];
      this.trigger.pos.y = params[3];
      this.trigger.exit = this;
      this.isOpen = false;
      this.mc._xscale = this.mc._yscale = this.r * 2;
      this.mc._x = this.pos.x;
      this.mc._y = this.pos.y;
      this.mc.gotoAndStop("exit_closed");
      this.mc._visible = true;
      this.trigger.mc._xscale = this.trigger.mc._yscale = this.trigger.r * 2;
      this.trigger.mc._x = this.trigger.pos.x;
      this.trigger.mc._y = this.trigger.pos.y;
      this.trigger.mc.gotoAndStop("exit_closed");
      this.trigger.mc._visible = true;
      this.trigger.TestVsPlayer = this.TestVsPlayer_Trigger;
      this.TestVsPlayer = this.TestVsPlayer_Exit;
      objects.AddToGrid(this.trigger);
      objects.Moved(this.trigger);
   }
};
ExitObject.prototype.UnInit = function()
{
   objects.RemoveFromGrid(this);
   objects.RemoveFromGrid(this.trigger);
};
ExitObject.prototype.DumpInitData = function()
{
   var _loc2_ = "" + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y + OBJPARAM_SEPERATION_CHAR + this.trigger.pos.x + OBJPARAM_SEPERATION_CHAR + this.trigger.pos.y;
   return _loc2_;
};
ExitObject.prototype.IdleAfterDeath = function()
{
   objects.RemoveFromGrid(this);
   objects.RemoveFromGrid(this.trigger);
};
ExitObject.prototype.TestVsPlayer_Exit = function(guy)
{
   var _loc5_;
   var _loc3_;
   var _loc2_;
   if(this.isOpen)
   {
      _loc5_ = guy.pos;
      _loc3_ = this.pos.x - guy.pos.x;
      _loc2_ = this.pos.y - guy.pos.y;
      if(Math.sqrt(_loc3_ * _loc3_ + _loc2_ * _loc2_) < this.r + guy.r)
      {
         this.PlayerHitExit();
      }
   }
};
ExitObject.prototype.TestVsPlayer_Trigger = function(guy)
{
   var _loc5_;
   var _loc3_;
   var _loc2_;
   if(!this.exit.isOpen)
   {
      _loc5_ = guy.pos;
      _loc3_ = this.pos.x - guy.pos.x;
      _loc2_ = this.pos.y - guy.pos.y;
      if(Math.sqrt(_loc3_ * _loc3_ + _loc2_ * _loc2_) < this.r + guy.r)
      {
         this.exit.PlayerHitTrigger();
      }
   }
};
ExitObject.prototype.PlayerHitExit = function()
{
   player.Celebrate();
   App_LevelPassedEvent();
};
ExitObject.prototype.PlayerHitTrigger = function()
{
   this.mc.gotoAndPlay("exit_opening");
   this.isOpen = true;
   this.trigger.mc.gotoAndStop("exit_open");
   objects.RemoveFromGrid(this.trigger);
   objects.AddToGrid(this);
   objects.Moved(this);
};
