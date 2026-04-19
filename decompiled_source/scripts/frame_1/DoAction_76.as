function HomingLauncherObject()
{
   this.name = "homing rocket";
   this.basepos = new Vector2(3,8);
   this.view = new Vector2(4,56);
   this.pos = new Vector2(0,9);
   this.mdir = new Vector2(7,6);
   this.speed = 0;
   this.maxspeed = tiles.xw * 0.2857142857142857;
   this.startaccel = 0.1;
   this.curaccel = this.startaccel;
   this.accelrate = 1.1;
   this.turnrate = 0.1;
   this.isHoming = false;
   this.prefireDelay = 10;
   this.fireDelayTimer = 0;
   objects.Register(this);
   this.mc = gfx.CreateSprite("debugHomingLauncherMC",LAYER_WALLS);
   this.rocketmc = gfx.CreateSprite("debugHomingRocketMC",LAYER_OBJECTS);
   this.mc._visible = false;
   this.rocketmc._visible = true;
   this.mc.gotoAndStop("rocket_waiting");
   this.snd = new Sound(this.mc);
}
HomingLauncherObject.prototype.Destruct = function()
{
   gfx.DestroyMC(this.mc);
   delete this.mc;
   gfx.DestroyMC(this.rocketmc);
   delete this.rocketmc;
   delete this.snd;
};
HomingLauncherObject.prototype.Init = function(params)
{
   if(params.length == 2)
   {
      this.basepos.x = params[0];
      this.basepos.y = params[1];
      this.StartIdle();
      this.mc._xscale = this.mc._yscale = tiles.xw;
      this.mc._x = this.basepos.x;
      this.mc._y = this.basepos.y;
      this.mc._visible = true;
      this.mc.gotoAndStop("rocket_waiting");
      this.rocketmc._xscale = this.rocketmc._yscale = 100;
      this.rocketmc._x = this.basepos.x;
      this.rocketmc._y = this.basepos.y;
      this.rocketmc._visible = false;
   }
};
HomingLauncherObject.prototype.UnInit = function()
{
   objects.RemoveFromGrid(this);
   objects.EndUpdate(this);
   objects.EndThink(this);
};
HomingLauncherObject.prototype.DumpInitData = function()
{
   var _loc2_ = "" + this.basepos.x + OBJPARAM_SEPERATION_CHAR + this.basepos.y;
   return _loc2_;
};
HomingLauncherObject.prototype.IdleAfterDeath = function()
{
   if(this.isHoming)
   {
      this.StartIdle = this.StartIdle_Death;
   }
   else
   {
      objects.EndThink(this);
   }
};
HomingLauncherObject.prototype.StartIdle_Death = function()
{
   this.isHoming = false;
};
HomingLauncherObject.prototype.Draw = function()
{
   this.rocketmc._x = this.pos.x;
   this.rocketmc._y = this.pos.y;
   var _loc2_ = NormToRot(this.mdir.x,this.mdir.y);
   this.rocketmc._rotation = _loc2_;
   particles.SpawnRocketSmoke(this.pos,_loc2_);
};
HomingLauncherObject.prototype.StartFiring = function()
{
   objects.EndThink(this);
   objects.StartUpdate(this);
   this.isHoming = true;
   this.fireDelayTimer = 0;
   this.Update = this.Update_PreFire;
};
HomingLauncherObject.prototype.StartIdle = function()
{
   this.isHoming = false;
   objects.StartThink(this);
};
HomingLauncherObject.prototype.FireMissile = function()
{
   this.curaccel = this.startaccel;
   this.speed = 0;
   this.pos.x = this.basepos.x;
   this.pos.y = this.basepos.y;
   objects.AddToGrid(this);
   objects.StartDraw(this);
   this.Update = this.Update_Homing;
   var _loc2_ = player.pos.x - this.basepos.x;
   var _loc3_ = player.pos.y - this.basepos.y;
   var _loc4_ = Math.sqrt(_loc2_ * _loc2_ + _loc3_ * _loc3_);
   if(_loc4_ != 0)
   {
      _loc2_ /= _loc4_;
      _loc3_ /= _loc4_;
      this.mdir.x = _loc2_;
      this.mdir.y = _loc3_;
   }
   trace("FRAME " + game.tickCounter + " Homing launcher " + this.UID + " firing missile at direction " + this.mdir.x + ", " + this.mdir.y + ".");
   this.rocketmc._visible = true;
   this.mc.gotoAndPlay("rocket_fire");
};
HomingLauncherObject.prototype.ExplodeMissile = function()
{
   this.snd.stop();
   this.rocketmc._visible = false;
   this.mc.gotoAndPlay("rocket_explode");
   particles.SpawnExplosion(this.pos);
   objects.EndUpdate(this);
   objects.EndDraw(this);
   objects.RemoveFromGrid(this);
   this.StartIdle();
};
HomingLauncherObject.prototype.Think = function()
{
   trace("FRAME " + game.tickCounter + " Homing launcher " + this.UID + " checking for player.");
   if (!_root.patch_options.recording) {
      var _loc2_ = gfx.CreateEmptySprite(LAYER_OBJECTS);
      _loc2_._x = this.basepos.x;
      _loc2_._y = this.basepos.y;
      _loc2_.clear();
      _loc2_.lineStyle(2,16711935,100);
      _loc2_.moveTo(0,0);
      _loc2_.lineTo(player.pos.x - this.basepos.x,player.pos.y - this.basepos.y);
      _loc2_.__ttl = 3;
      _loc2_.onEnterFrame = function()
      {
         this.__ttl--;
         if(this.__ttl <= 0)
         {
            this.onEnterFrame = null;
            this.removeMovieClip();
         }
      };
   }
   if(QueryRayObj(this.view,this.basepos,player.pos,player))
   {
      trace("FRAME " + game.tickCounter + " Homing launcher " + this.UID + " detected player.");
      this.StartFiring();
   }
};
HomingLauncherObject.prototype.TestVsPlayer = function(guy)
{
   var _loc3_ = guy.pos.x - this.pos.x;
   var _loc4_ = guy.pos.y - this.pos.y;
   var _loc5_ = Math.sqrt(_loc3_ * _loc3_ + _loc4_ * _loc4_);
   if(_loc5_ < player.r)
   {
      game.KillPlayer(KILLTYPE_EXPLOSIVE,_loc3_,_loc4_,this.pos.x,this.pos.y,this);
      this.ExplodeMissile();
      return undefined;
   }
};
HomingLauncherObject.prototype.Update_PreFire = function()
{
   this.fireDelayTimer += 1;
   if(this.prefireDelay <= this.fireDelayTimer)
   {
      this.FireMissile();
   }
};
HomingLauncherObject.prototype.Update_Homing = function()
{
   var _loc2_ = this.pos;
   if(this.speed < this.maxspeed)
   {
      this.curaccel *= this.accelrate;
      this.speed += this.curaccel;
   }
   else
   {
      this.speed = this.maxspeed;
   }
   _loc2_.x += this.speed * this.mdir.x;
   _loc2_.y += this.speed * this.mdir.y;
   if(QueryPointvsTileMap(_loc2_.x,_loc2_.y))
   {
      this.ExplodeMissile();
      return undefined;
   }
   var _loc3_ = this.cell;
   var _loc4_;
   var _loc5_;
   if(objects.Moved(this))
   {
      _loc4_ = this.cell;
      if(_loc4_ == _loc3_.nR)
      {
         _loc5_ = _loc3_.eR;
      }
      else if(_loc4_ == _loc3_.nL)
      {
         _loc5_ = _loc3_.eL;
      }
      else if(_loc4_ == _loc3_.nU)
      {
         _loc5_ = _loc3_.eU;
      }
      else if(_loc4_ == _loc3_.nD)
      {
         _loc5_ = _loc3_.eD;
      }
      else
      {
         _loc5_ = EID_OFF;
      }
      if(_loc5_ == EID_SOLID)
      {
         this.ExplodeMissile();
         return undefined;
      }
   }
   var _loc6_ = player;
   dx = 2 * _loc6_.pos.x - _loc6_.oldpos.x - (_loc2_.x + this.speed * this.mdir.x);
   dy = 2 * _loc6_.pos.y - _loc6_.oldpos.y - (_loc2_.y + this.speed * this.mdir.y);
   var _loc7_ = Math.sqrt(dx * dx + dy * dy);
   dx /= _loc7_;
   dy /= _loc7_;
   var _loc8_ = this.mdir.x * dx + this.mdir.y * dy;
   var _loc9_ = (- this.mdir.y) * dx + this.mdir.x * dy;
   var _loc10_ = this.turnrate;
   if(_loc8_ < 0)
   {
   }
   var _loc11_ = _loc9_ * (- this.mdir.y);
   var _loc12_ = _loc9_ * this.mdir.x;
   this.mdir.x += _loc11_ * _loc10_;
   this.mdir.y += _loc12_ * _loc10_;
   _loc7_ = Math.sqrt(this.mdir.x * this.mdir.x + this.mdir.y * this.mdir.y);
   if(_loc7_ == 0)
   {
      return undefined;
   }
   this.mdir.x /= _loc7_;
   this.mdir.y /= _loc7_;
};
