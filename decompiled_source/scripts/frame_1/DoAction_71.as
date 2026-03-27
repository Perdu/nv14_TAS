function BounceBlockObject()
{
   this.name = "bounce block";
   this.xw = tiles.xw * 0.8;
   this.yw = tiles.yw * 0.8;
   this.pos = new Vector2(10,20);
   this.oldpos = new Vector2(30,40);
   this.anchor = new Vector2(50,60);
   this.stiff = 0.05;
   this.mass = 0.2;
   this.ASLEEP = true;
   this.sleepThreshold = 40;
   this.sleepTimer = 0;
   this.touchingObj = null;
   objects.Register(this);
   this.mc = gfx.CreateSprite("debugBounceBlockMC",LAYER_OBJECTS);
   this.mc._visible = false;
}
BounceBlockObject.prototype.Destruct = function()
{
   gfx.DestroyMC(this.mc);
   delete this.mc;
};
BounceBlockObject.prototype.Init = function(params)
{
   if(params.length == 2)
   {
      this.pos.x = this.oldpos.x = this.anchor.x = params[0];
      this.pos.y = this.oldpos.y = this.anchor.y = params[1];
      this.mc._xscale = 2 * this.xw;
      this.mc._yscale = 2 * this.yw;
      this.Draw();
      this.mc._visible = true;
      objects.AddToGrid(this);
      objects.Moved(this);
   }
};
BounceBlockObject.prototype.UnInit = function()
{
   objects.RemoveFromGrid(this);
   objects.EndDraw(this);
   objects.EndUpdate(this);
   objects.EndThink(this);
};
BounceBlockObject.prototype.DumpInitData = function()
{
   var _loc2_ = "" + this.anchor.x + OBJPARAM_SEPERATION_CHAR + this.anchor.y;
   return _loc2_;
};
BounceBlockObject.prototype.IdleAfterDeath = function()
{
};
BounceBlockObject.prototype.Draw = function()
{
   this.mc._x = this.pos.x;
   this.mc._y = this.pos.y;
};
BounceBlockObject.prototype.TestVsRagParticle = function(rp)
{
   var _loc7_ = rp.pos;
   var _loc5_ = _loc7_.y - this.pos.y;
   var _loc2_ = this.yw + rp.yw - Math.abs(_loc5_);
   var _loc6_;
   var _loc3_;
   var _loc8_;
   var _loc9_;
   if(0 < _loc2_)
   {
      _loc6_ = _loc7_.x - this.pos.x;
      _loc3_ = this.xw + rp.xw - Math.abs(_loc6_);
      if(0 < _loc3_)
      {
         if(_loc2_ < _loc3_)
         {
            if(_loc5_ <= 0)
            {
               _loc8_ = -1;
               _loc2_ *= -1;
            }
            else
            {
               _loc8_ = 1;
            }
            this.pos.y -= (1 - this.mass) * _loc2_;
            rp.ReportCollisionVsObject(0,this.mass * _loc2_,0,_loc8_,0.3);
         }
         else
         {
            if(_loc6_ < 0)
            {
               _loc3_ *= -1;
               _loc9_ = -1;
            }
            else
            {
               _loc9_ = 1;
            }
            this.pos.x -= (1 - this.mass) * _loc3_;
            rp.ReportCollisionVsObject(this.mass * _loc3_,0,_loc9_,0,0.3);
         }
         this.sleepTimer = 0;
         if(this.ASLEEP)
         {
            this.Wake();
         }
         this.touchingObj = guy;
         return undefined;
      }
   }
   this.touchingOBj = null;
};
BounceBlockObject.prototype.TestVsPlayer = function(guy)
{
   var _loc7_ = guy.pos;
   var _loc5_ = _loc7_.y - this.pos.y;
   var _loc2_ = this.yw + guy.yw - Math.abs(_loc5_);
   var _loc6_;
   var _loc3_;
   var _loc8_;
   var _loc9_;
   if(0 < _loc2_)
   {
      _loc6_ = _loc7_.x - this.pos.x;
      _loc3_ = this.xw + guy.xw - Math.abs(_loc6_);
      if(0 < _loc3_)
      {
         if(_loc2_ < _loc3_)
         {
            if(_loc5_ < 0)
            {
               _loc8_ = -1;
               _loc2_ *= -1;
            }
            else
            {
               _loc8_ = 1;
            }
            this.pos.y -= (1 - this.mass) * _loc2_;
            guy.ReportCollisionVsObject(0,this.mass * _loc2_,0,_loc8_,this);
         }
         else
         {
            if(_loc6_ < 0)
            {
               _loc3_ *= -1;
               _loc9_ = -1;
            }
            else
            {
               _loc9_ = 1;
            }
            this.pos.x -= (1 - this.mass) * _loc3_;
            guy.ReportCollisionVsObject(this.mass * _loc3_,0,_loc9_,0,this);
         }
         this.sleepTimer = 0;
         if(this.ASLEEP)
         {
            this.Wake();
         }
         this.touchingObj = guy;
         return undefined;
      }
   }
   this.touchingOBj = null;
};
BounceBlockObject.prototype.Wake = function()
{
   objects.StartUpdate(this);
   objects.StartThink(this);
   objects.StartDraw(this);
   this.ASLEEP = false;
};
BounceBlockObject.prototype.Sleep = function()
{
   objects.EndUpdate(this);
   objects.EndThink(this);
   objects.EndDraw(this);
   this.ASLEEP = true;
   this.oldpos.x = this.pos.x;
   this.oldpos.y = this.pos.y;
};
BounceBlockObject.prototype.Think = function()
{
   if(this.sleepThreshold < this.sleepTimer)
   {
      this.Sleep();
   }
};
BounceBlockObject.prototype.Update = function()
{
   var _loc2_ = this.pos;
   var _loc3_ = this.oldpos;
   var _loc9_;
   var _loc8_;
   var _loc7_;
   var _loc6_;
   _loc9_ = _loc3_.x;
   _loc8_ = _loc3_.y;
   var _loc0_;
   _loc7_ = _loc3_.x = _loc2_.x;
   _loc6_ = _loc3_.y = _loc2_.y;
   _loc2_.x += 0.99 * (_loc7_ - _loc9_);
   _loc2_.y += 0.99 * (_loc6_ - _loc8_);
   var _loc5_ = this.anchor.x - _loc2_.x;
   var _loc4_ = this.anchor.y - _loc2_.y;
   if(0 < _loc5_ * _loc5_ + _loc4_ * _loc4_)
   {
      _loc2_.x += _loc5_ * this.stiff;
      _loc2_.y += _loc4_ * this.stiff;
      if(this.touchingObj != null)
      {
      }
   }
   this.sleepTimer = this.sleepTimer + 1;
};
