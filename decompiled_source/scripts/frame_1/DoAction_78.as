function MineObject()
{
   this.name = "mine";
   this.pos = new Vector2(43,16);
   this.r = tiles.xw * 0.3333333333333333;
   objects.Register(this);
   this.mc = gfx.CreateSprite("debugMineMC",LAYER_OBJECTS);
   this.mc._visible = false;
}
MineObject.prototype.Destruct = function()
{
   gfx.DestroyMC(this.mc);
   delete this.mc;
};
MineObject.prototype.Init = function(params)
{
   if(params.length == 2)
   {
      this.pos.x = params[0];
      this.pos.y = params[1];
      objects.AddToGrid(this);
      objects.Moved(this);
      this.mc._xscale = this.mc._yscale = 2 * this.r;
      this.mc._x = this.pos.x;
      this.mc._y = this.pos.y;
      this.mc.gotoAndStop("mine_unexploded");
      this.mc._visible = true;
   }
};
MineObject.prototype.UnInit = function()
{
   objects.RemoveFromGrid(this);
};
MineObject.prototype.DumpInitData = function()
{
   var _loc2_ = "" + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y;
   return _loc2_;
};
MineObject.prototype.IdleAfterDeath = function()
{
};
MineObject.prototype.TestVsPlayer = function(guy)
{
   var _loc4_ = guy.pos;
   var _loc3_ = this.pos.x - _loc4_.x;
   var _loc2_ = this.pos.y - _loc4_.y;
   if(Math.sqrt(_loc3_ * _loc3_ + _loc2_ * _loc2_) < this.r + guy.r)
   {
      this.Explode(- _loc3_,- _loc2_);
   }
};
MineObject.prototype.TestVsRagParticle = function(guy)
{
   var _loc5_ = guy.pos;
   var _loc4_ = this.pos.x - _loc5_.x;
   var _loc3_ = this.pos.y - _loc5_.y;
   var _loc2_ = Math.sqrt(_loc4_ * _loc4_ + _loc3_ * _loc3_);
   if(_loc2_ < this.r + guy.xw)
   {
      player.RagDie(KILLTYPE_EXPLOSIVE);
      guy.ReportCollisionVsObject((- _loc4_) / _loc2_ * 16,(- _loc3_) / _loc2_ * 16,(- _loc4_) / _loc2_,(- _loc3_) / _loc2_,1);
      this.ExplodeRag(- _loc4_,- _loc3_);
   }
};
MineObject.prototype.Explode = function(dx, dy)
{
   game.KillPlayer(KILLTYPE_EXPLOSIVE,dx,dy,this.pos.x,this.pos.y,this);
   particles.SpawnExplosion(this.pos);
   objects.RemoveFromGrid(this);
   this.mc.gotoAndStop("mine_exploded");
};
MineObject.prototype.ExplodeRag = function(dx, dy)
{
   particles.SpawnExplosion(this.pos);
   objects.RemoveFromGrid(this);
   this.mc.gotoAndStop("mine_exploded");
};
