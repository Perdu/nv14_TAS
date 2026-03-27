function LaunchPadObject()
{
   this.name = "launch pad";
   this.pos = new Vector2(54,23);
   this.nx = 0;
   this.ny = 1;
   this.r = tiles.xw * 0.5;
   this.strength = tiles.xw * 0.42857142857142855;
   objects.Register(this);
   this.mc = gfx.CreateSprite("debugLaunchPadMC",LAYER_WALLS);
   this.mc._visible = false;
}
LaunchPadObject.prototype.Destruct = function()
{
   gfx.DestroyMC(this.mc);
   delete this.mc;
};
LaunchPadObject.prototype.Init = function(params)
{
   if(params.length == 4)
   {
      this.pos.x = params[0];
      this.pos.y = params[1];
      this.nx = params[2];
      this.ny = params[3];
      this.mc._xscale = this.mc._yscale = 2.5 * this.r;
      this.mc._x = this.pos.x;
      this.mc._y = this.pos.y;
      this.mc._visible = true;
      this.mc.gotoAndStop("launch_idle");
      if(this.nx < 0)
      {
         if(this.ny < 0)
         {
            this.mc._rotation = -45;
         }
         else if(0 < this.ny)
         {
            this.mc._rotation = -135;
         }
         else
         {
            this.mc._rotation = -90;
         }
      }
      else if(0 < this.nx)
      {
         if(this.ny < 0)
         {
            this.mc._rotation = 45;
         }
         else if(0 < this.ny)
         {
            this.mc._rotation = 135;
         }
         else
         {
            this.mc._rotation = 90;
         }
      }
      else if(this.ny < 0)
      {
         this.mc._rotation = 0;
      }
      else if(0 < this.ny)
      {
         this.mc._rotation = 180;
      }
      objects.AddToGrid(this);
      objects.Moved(this);
   }
};
LaunchPadObject.prototype.UnInit = function()
{
   objects.RemoveFromGrid(this);
};
LaunchPadObject.prototype.DumpInitData = function()
{
   var _loc2_ = "" + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y + OBJPARAM_SEPERATION_CHAR + this.nx + OBJPARAM_SEPERATION_CHAR + this.ny;
   return _loc2_;
};
LaunchPadObject.prototype.IdleAfterDeath = function()
{
};
LaunchPadObject.prototype.TestVsPlayer = function(guy)
{
   var _loc6_ = guy.pos;
   var _loc5_ = this.pos.x - guy.pos.x;
   var _loc4_ = this.pos.y - guy.pos.y;
   var _loc2_ = guy.r;
   var _loc9_;
   var _loc8_;
   var _loc10_;
   var _loc7_;
   if(Math.sqrt(_loc5_ * _loc5_ + _loc4_ * _loc4_) < this.r + _loc2_)
   {
      _loc9_ = this.pos.x - (_loc6_.x - this.nx * _loc2_);
      _loc8_ = this.pos.y - (_loc6_.y - this.ny * _loc2_);
      _loc10_ = _loc9_ * this.nx + _loc8_ * this.ny;
      if(0 <= _loc10_)
      {
         _loc7_ = 1;
         if(this.ny < 0)
         {
            _loc7_ += Math.abs(this.ny);
         }
         this.mc.gotoAndPlay("launch_triggered");
         guy.Launch(this.nx * this.strength,this.ny * this.strength * _loc7_);
      }
   }
};
LaunchPadObject.prototype.TestVsRagParticle = function(guy)
{
   var _loc6_ = guy.pos;
   var _loc4_ = this.pos.x - guy.pos.x;
   var _loc3_ = this.pos.y - guy.pos.y;
   var _loc5_ = guy.xw;
   if(Math.sqrt(_loc4_ * _loc4_ + _loc3_ * _loc3_) < this.r + _loc5_)
   {
      this.mc.gotoAndPlay("launch_triggered");
      guy.ReportCollisionVsObject(this.nx * 12,this.ny * 12,1,0,1);
   }
};
