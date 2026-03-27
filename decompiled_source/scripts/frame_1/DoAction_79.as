function FloorGuardObject()
{
   this.name = "floor guard";
   this.pos = new Vector2(41,14);
   this.r = tiles.xw * 0.5;
   this.dir = 1;
   this.speed = tiles.xw * 0.42857142857142855;
   this.view = new Vector2(0,0);
   objects.Register(this);
   this.mc = gfx.CreateSprite("debugFloorGuardMC",LAYER_OBJECTS);
   this.mc._visible = false;
   this.mc.gotoAndStop("floorguard_idle");
}
FloorGuardObject.prototype.Destruct = function()
{
   gfx.DestroyMC(this.mc);
   delete this.mc;
};
FloorGuardObject.prototype.Init = function(params)
{
   var _loc2_;
   if(params.length == 3)
   {
      this.pos.x = params[0];
      this.pos.y = params[1];
      if(dir < 0)
      {
         this.dir = -1;
      }
      else
      {
         this.dir = 1;
      }
      objects.AddToGrid(this);
      objects.Moved(this);
      objects.StartUpdate(this);
      this.Update = this.Update_Idle;
      this.pos.y = this.cell.pos.y + this.cell.yw - this.r;
      _loc2_ = this.cell;
      while(true)
      {
         _loc2_ = _loc2_.nR;
         if(TID_EMPTY < _loc2_.ID || _loc2_.eD != EID_SOLID)
         {
            this.maxX = _loc2_.pos.x - _loc2_.xw - this.r;
            break;
         }
      }
      while(true)
      {
         _loc2_ = _loc2_.nL;
         if(TID_EMPTY < _loc2_.ID || _loc2_.eD != EID_SOLID)
         {
            this.minX = _loc2_.pos.x + _loc2_.xw + this.r;
            break;
         }
      }
      _loc2_ = this.cell;
      this.mini = _loc2_.i;
      this.maxi = _loc2_.i;
      while(true)
      {
         _loc2_ = _loc2_.nR;
         if(TID_EMPTY < _loc2_.ID)
         {
            break;
         }
         this.maxi = this.maxi + 1;
      }
      _loc2_ = this.cell;
      while(true)
      {
         _loc2_ = _loc2_.nL;
         if(TID_EMPTY < _loc2_.ID)
         {
            break;
         }
         this.mini = this.mini - 1;
      }
      this.mc._xscale = this.mc._yscale = 2 * this.r;
      this.Draw();
      this.mc._visible = true;
   }
};
FloorGuardObject.prototype.UnInit = function()
{
   objects.RemoveFromGrid(this);
   objects.EndUpdate(this);
   objects.EndDraw(this);
};
FloorGuardObject.prototype.DumpInitData = function()
{
   var _loc2_ = "" + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y + OBJPARAM_SEPERATION_CHAR + this.dir;
   return _loc2_;
};
FloorGuardObject.prototype.IdleAfterDeath = function()
{
   this.StopChasing();
   objects.EndUpdate(this);
};
FloorGuardObject.prototype.Draw = function()
{
   this.mc._x = this.pos.x;
   this.mc._y = this.pos.y;
};
FloorGuardObject.prototype.TestVsPlayer = function(guy)
{
   var _loc4_ = guy.pos;
   var _loc3_ = this.pos.x - _loc4_.x;
   var _loc2_ = this.pos.y - _loc4_.y;
   var _loc5_ = Math.sqrt(_loc3_ * _loc3_ + _loc2_ * _loc2_);
   if(_loc5_ < this.r + guy.r)
   {
      _loc3_ /= _loc5_;
      _loc2_ /= _loc5_;
      particles.SpawnZap(this.pos.x - _loc3_ * this.r,this.pos.y - _loc2_ * this.r,NormToRot(- _loc3_,- _loc2_));
      game.KillPlayer(KILLTYPE_ELECTRIC,(- _loc3_) * 10,(- _loc2_) * 10,_loc4_.x + guy.r * _loc3_,_loc4_.y + guy.r * _loc2_,this);
   }
};
FloorGuardObject.prototype.TestVsRagParticle = function(guy)
{
   var _loc5_ = guy.pos;
   var _loc3_ = this.pos.x - _loc5_.x;
   var _loc2_ = this.pos.y - _loc5_.y;
   var _loc4_ = Math.sqrt(_loc3_ * _loc3_ + _loc2_ * _loc2_);
   if(_loc4_ < this.r + guy.xw)
   {
      _loc3_ /= _loc4_;
      _loc2_ /= _loc4_;
      particles.SpawnZap(this.pos.x - _loc3_ * this.r,this.pos.y - _loc2_ * this.r,NormToRot(- _loc3_,- _loc2_));
      player.RagDie(KILLTYPE_ELECTRIC);
      guy.ReportCollisionVsObject((- _loc3_) * 12,(- _loc2_) * 12,- _loc3_,- _loc2_,1);
   }
};
FloorGuardObject.prototype.StartChasing = function()
{
   this.Update = this.Update_Chase;
   objects.StartDraw(this);
   this.mc.gotoAndStop("floorguard_active");
   if(player.cell.i < this.cell.i)
   {
      this.dir = -1;
   }
   else if(this.cell.i < player.cell.i)
   {
      this.dir = 1;
   }
   else
   {
      this.StopChasing();
   }
};
FloorGuardObject.prototype.StopChasing = function()
{
   this.mc.gotoAndStop("floorguard_idle");
   this.Update = this.Update_Idle;
   objects.EndDraw(this);
};
FloorGuardObject.prototype.Update_Idle = function()
{
   var _loc2_;
   if(Math.abs(this.cell.j - player.cell.j) == 0)
   {
      _loc2_ = player.cell.i;
      if(!(this.maxi < _loc2_ || _loc2_ < this.mini))
      {
         this.StartChasing();
      }
   }
};
FloorGuardObject.prototype.Update_Chase = function()
{
   if(this.dir < 0)
   {
      if(Math.abs(this.pos.x - this.minX) < this.speed)
      {
         this.pos.x = this.minX;
         this.StopChasing();
      }
      else
      {
         this.pos.x += this.dir * this.speed;
      }
   }
   else if(Math.abs(this.maxX - this.pos.x) < this.speed)
   {
      this.pos.x = this.maxX;
      this.StopChasing();
   }
   else
   {
      this.pos.x += this.dir * this.speed;
   }
   objects.Moved(this);
};
