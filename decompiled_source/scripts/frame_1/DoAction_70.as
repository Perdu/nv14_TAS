function Init_Hacky_GoldSound()
{
   _global.goldSnd = gfx.CreateSprite("debugGoldSoundMC",LAYER_PLAYER);
}
function GoldObject()
{
   this.name = "gold";
   this.pos = new Vector2(14,65);
   this.isCollected = false;
   this.r = tiles.xw * 0.5;
   objects.Register(this);
   this.mc = gfx.CreateSprite("debugGoldMC",LAYER_OBJECTS);
   this.mc._visible = false;
}
GoldObject.prototype.Destruct = function()
{
   gfx.DestroyMC(this.mc);
   delete this.mc;
};
GoldObject.prototype.Init = function(params)
{
   if(params.length == 2)
   {
      this.pos.x = params[0];
      this.pos.y = params[1];
      this.isCollected = false;
      this.mc._xscale = this.mc._yscale = this.r;
      this.mc._x = this.pos.x;
      this.mc._y = this.pos.y;
      this.mc._visible = true;
      this.mc.gotoAndStop("NOT_COLLECTED");
      objects.AddToGrid(this);
      objects.Moved(this);
   }
};
GoldObject.prototype.UnInit = function()
{
   objects.RemoveFromGrid(this);
};
GoldObject.prototype.DumpInitData = function()
{
   var _loc2_ = "" + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y;
   return _loc2_;
};
GoldObject.prototype.IdleAfterDeath = function()
{
   if(!this.isCollected)
   {
      objects.RemoveFromGrid(this);
   }
};
GoldObject.prototype.TestVsPlayer = function(guy)
{
   var _loc5_ = guy.pos;
   var _loc3_ = this.pos.x - guy.pos.x;
   var _loc2_ = this.pos.y - guy.pos.y;
   if(Math.sqrt(_loc3_ * _loc3_ + _loc2_ * _loc2_) < this.r + guy.r)
   {
      this.Dissapear();
   }
};
GoldObject.prototype.Dissapear = function()
{
   this.isCollected = true;
   objects.RemoveFromGrid(this);
   this.mc.gotoAndPlay("COLLECTED");
   _global.goldSnd.gotoAndPlay("COLLECTED");
   game.GiveBonusTime();
};
