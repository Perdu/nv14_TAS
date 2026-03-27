function OneWayPlatformObject()
{
   this.name = "oneway block";
   this.xw = tiles.xw;
   this.yw = tiles.xw;
   this.pos = new Vector2(10,20);
   this.dir = new Vector2(0,1);
   this.dirEnum = AI_DIR_U;
   objects.Register(this);
   this.mc = gfx.CreateSprite("debugOneWayPlatformMC",LAYER_WALLS);
   this.mc._visible = false;
}
OneWayPlatformObject.prototype.Destruct = function()
{
   gfx.DestroyMC(this.mc);
   delete this.mc;
};
OneWayPlatformObject.prototype.Init = function(params)
{
   var _loc2_;
   if(params.length == 3)
   {
      this.pos.x = params[0];
      this.pos.y = params[1];
      _loc2_ = params[2];
      this.dirEnum = _loc2_;
      if(_loc2_ == AI_DIR_U)
      {
         this.dir.x = 0;
         this.dir.y = -1;
      }
      else if(_loc2_ == AI_DIR_D)
      {
         this.dir.x = 0;
         this.dir.y = 1;
         this.mc._rotation = 180;
      }
      else if(_loc2_ == AI_DIR_L)
      {
         this.dir.x = -1;
         this.dir.y = 0;
         this.mc._rotation = -90;
      }
      else if(_loc2_ == AI_DIR_R)
      {
         this.dir.x = 1;
         this.dir.y = 0;
         this.mc._rotation = 90;
      }
      this.mc._x = this.pos.x;
      this.mc._y = this.pos.y;
      this.mc._xscale = 2 * this.xw;
      this.mc._yscale = 2 * this.yw;
      this.mc._visible = true;
      objects.AddToGrid(this);
      objects.Moved(this);
   }
};
OneWayPlatformObject.prototype.UnInit = function()
{
   objects.RemoveFromGrid(this);
};
OneWayPlatformObject.prototype.DumpInitData = function()
{
   var _loc2_ = "" + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y + OBJPARAM_SEPERATION_CHAR + this.dirEnum;
   return _loc2_;
};
OneWayPlatformObject.prototype.IdleAfterDeath = function()
{
};
OneWayPlatformObject.prototype.TestVsPlayer = function(guy)
{
   var _loc3_ = guy.pos;
   var _loc7_ = _loc3_.y - this.pos.y;
   var _loc9_ = this.yw + guy.yw - Math.abs(_loc7_);
   var _loc8_;
   var _loc10_;
   var _loc4_;
   var _loc11_;
   var _loc5_;
   var _loc6_;
   if(0 < _loc9_)
   {
      _loc8_ = _loc3_.x - this.pos.x;
      _loc10_ = this.xw + guy.xw - Math.abs(_loc8_);
      if(0 < _loc10_)
      {
         if(this.dir.x == 0)
         {
            _loc4_ = guy.pos.y - guy.oldpos.y;
            if(_loc4_ * this.dir.y <= 0)
            {
               _loc11_ = guy.oldpos.y - this.dir.y * guy.yw - (this.pos.y + this.dir.y * this.yw);
               if(0 <= _loc11_ * this.dir.y)
               {
                  _loc5_ = this.pos.y + this.dir.y * this.yw - (guy.pos.y - this.dir.y * guy.yw);
                  guy.ReportCollisionVsObject(0,_loc5_,0,this.dir.y,this);
               }
            }
         }
         else
         {
            _loc4_ = guy.pos.x - guy.oldpos.x;
            if(_loc4_ * this.dir.x <= 0)
            {
               _loc11_ = guy.oldpos.x - this.dir.x * guy.xw - (this.pos.x + this.dir.x * this.xw);
               if(0 <= _loc11_ * this.dir.x)
               {
                  _loc6_ = this.pos.x + this.dir.x * this.xw - (guy.pos.x - this.dir.x * guy.xw);
                  guy.ReportCollisionVsObject(_loc6_,0,this.dir.x,0,this);
               }
            }
         }
      }
   }
};
OneWayPlatformObject.prototype.TestVsRagParticle = function(guy)
{
   var _loc3_ = guy.pos;
   var _loc7_ = _loc3_.y - this.pos.y;
   var _loc9_ = this.yw + guy.yw - Math.abs(_loc7_);
   var _loc8_;
   var _loc10_;
   var _loc4_;
   var _loc11_;
   var _loc5_;
   var _loc6_;
   if(0 < _loc9_)
   {
      _loc8_ = _loc3_.x - this.pos.x;
      _loc10_ = this.xw + guy.xw - Math.abs(_loc8_);
      if(0 < _loc10_)
      {
         if(this.dir.x == 0)
         {
            _loc4_ = guy.pos.y - guy.oldpos.y;
            if(_loc4_ * this.dir.y <= 0)
            {
               _loc11_ = guy.oldpos.y - this.dir.y * guy.yw - (this.pos.y + this.dir.y * this.yw);
               if(0 <= _loc11_ * this.dir.y)
               {
                  _loc5_ = this.pos.y + this.dir.y * this.yw - (guy.pos.y - this.dir.y * guy.yw);
                  guy.ReportCollisionVsObject(0,_loc5_,0,this.dir.y,0.3);
               }
            }
         }
         else
         {
            _loc4_ = guy.pos.x - guy.oldpos.x;
            if(_loc4_ * this.dir.x <= 0)
            {
               _loc11_ = guy.oldpos.x - this.dir.x * guy.xw - (this.pos.x + this.dir.x * this.xw);
               if(0 <= _loc11_ * this.dir.x)
               {
                  _loc6_ = this.pos.x + this.dir.x * this.xw - (guy.pos.x - this.dir.x * guy.xw);
                  guy.ReportCollisionVsObject(_loc6_,0,this.dir.x,0,0.3);
               }
            }
         }
      }
   }
};
