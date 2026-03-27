function TurretObject()
{
   this.name = "gauss turret";
   this.pos = new Vector2(21,12);
   objects.Register(this);
   this.view = new Vector2(0,0);
   this.targ = new Vector2(0,0);
   this.aim = new Vector2(this.pos.x,this.pos.y);
   this.closeAimSpeed = 0.05;
   this.midAimSpeed = 0.035;
   this.farAimSpeed = 0.03;
   this.aimSpeed = this.farAimSpeed;
   this.outerThreshold = tiles.xw * 8;
   this.innerThreshold = tiles.xw * 2;
   this.midThreshold = 0.25 * this.outerThreshold + 0.75 * this.innerThreshold;
   this.outerThreshold *= this.outerThreshold;
   this.midThreshold *= this.midThreshold;
   this.innerThreshold *= this.innerThreshold;
   this.shotRate = 60;
   this.shotTimer = 0;
   this.fireDelayTimer = 0;
   this.prefireDelay = 10;
   this.postfireDelay = 10;
   this.isFiring = false;
   this.mc = gfx.CreateSprite("debugTurretMC",LAYER_WALLS);
   this.mc._visible = false;
   this.crosshairMC = gfx.CreateSprite("debugTurretCrosshairMC",LAYER_OBJECTS);
   this.crosshairMC._visible = false;
}
TurretObject.prototype.Destruct = function()
{
   gfx.DestroyMC(this.mc);
   delete this.mc;
   gfx.DestroyMC(this.crosshairMC);
   delete this.crosshairMC;
};
TurretObject.prototype.Init = function(params)
{
   if(params.length == 2)
   {
      this.pos.x = this.aim.x = params[0];
      this.pos.y = this.aim.y = params[1];
      objects.StartThink(this);
      this.Think = this.Think_Waiting;
      this.mc._x = this.pos.x;
      this.mc._y = this.pos.y;
      this.mc._xscale = this.mc._yscale = tiles.xw;
      this.mc._visible = true;
      this.mc.gotoAndStop("turret_idle");
      this.crosshairMC._xscale = this.crosshairMC._yscale = tiles.xw * 1.5;
      this.crosshairMC._visible = false;
   }
};
TurretObject.prototype.UnInit = function()
{
   objects.EndThink(this);
   objects.EndUpdate(this);
   objects.EndDraw(this);
};
TurretObject.prototype.DumpInitData = function()
{
   var _loc2_ = "" + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y;
   return _loc2_;
};
TurretObject.prototype.Draw = function()
{
   this.crosshairMC._x = this.aim.x;
   this.crosshairMC._y = this.aim.y;
};
TurretObject.prototype.IdleAfterDeath = function()
{
   this.StopTargetting();
   objects.EndThink(this);
   objects.EndDraw(this);
};
TurretObject.prototype.StartFiring = function()
{
   this.crosshairMC.gotoAndStop("prefire");
   this.mc.gotoAndPlay("turret_prefire");
   objects.EndThink(this);
   objects.EndDraw(this);
   this.isFiring = true;
   this.fireDelayTimer = 0;
   this.Update = this.Update_PreFire;
};
TurretObject.prototype.StopFiring = function()
{
   objects.StartThink(this);
   this.Think = this.Think_Targetting;
   this.crosshairMC.gotoAndStop("postfire");
   this.mc.gotoAndPlay("turret_idle");
   this.isFiring = false;
   this.fireDelayTimer = 0;
   this.Update = this.Update_PostFire;
};
TurretObject.prototype.StartTargetting = function()
{
   this.crosshairMC._visible = true;
   this.crosshairMC.gotoAndStop("aim_far");
   this.aimSpeed = this.farAimSpeed;
   this.aim.x = this.pos.x;
   this.aim.y = this.pos.y;
   this.KeepTargetting();
};
TurretObject.prototype.StopTargetting = function()
{
   this.crosshairMC._visible = false;
   objects.EndUpdate(this);
   this.Think = this.Think_Waiting;
   objects.EndDraw(this);
};
TurretObject.prototype.KeepTargetting = function()
{
   this.shotTimer = this.shotRate;
   this.Update = this.Update_Targetting;
   this.Think = this.Think_Targetting;
   objects.StartUpdate(this);
   objects.StartDraw(this);
};
TurretObject.prototype.Fire = function()
{
   this.mc.gotoAndPlay("turret_firing");
   var _loc3_;
   var _loc2_;
   var _loc4_;
   var _loc5_;
   if(QueryRayObj(this.targ,this.pos,this.aim,player))
   {
      _loc3_ = this.aim.x - this.pos.x;
      _loc2_ = this.aim.y - this.pos.y;
      _loc4_ = Math.sqrt(_loc3_ * _loc3_ + _loc2_ * _loc2_);
      if(_loc4_ == 0)
      {
         _loc3_ = 1;
         _loc2_ = 1;
      }
      else
      {
         _loc3_ /= _loc4_;
         _loc2_ /= _loc4_;
      }
      game.KillPlayer(KILLTYPE_HARDBULLET,_loc3_ * 8,_loc2_ * 8,this.targ.x,this.targ.y,this);
      this.targ.x += _loc3_ * player.r;
      this.targ.y += _loc2_ * player.r;
      _loc5_ = NormToRot(_loc3_,_loc2_);
   }
   else
   {
      _loc3_ = this.aim.x - this.pos.x;
      _loc2_ = this.aim.y - this.pos.y;
      _loc4_ = Math.sqrt(_loc3_ * _loc3_ + _loc2_ * _loc2_);
      if(_loc4_ == 0)
      {
         _loc3_ = 1;
         _loc2_ = 1;
      }
      else
      {
         _loc3_ /= _loc4_;
         _loc2_ /= _loc4_;
      }
      _loc5_ = NormToRot(- _loc3_,- _loc2_);
   }
   particles.SpawnTurretBullet(this.pos,this.targ,_loc5_);
   this.StopFiring();
};
TurretObject.prototype.Think_Waiting = function()
{
   if(QueryRayObj(this.view,this.pos,player.pos,player))
   {
      this.StartTargetting();
   }
};
TurretObject.prototype.Think_Targetting = function()
{
   if(!QueryRayObj(this.view,this.pos,player.pos,player))
   {
      this.StopTargetting();
   }
};
TurretObject.prototype.Update_Targetting = function()
{
   var _loc7_ = 2 * player.pos.x - player.oldpos.x;
   var _loc6_ = 2 * player.pos.y - player.oldpos.y;
   var _loc2_ = this.aim;
   var _loc5_ = _loc2_.x - _loc7_;
   var _loc4_ = _loc2_.y - _loc6_;
   _loc2_.x -= this.aimSpeed * _loc5_;
   _loc2_.y -= this.aimSpeed * _loc4_;
   var _loc3_ = _loc5_ * _loc5_ + _loc4_ * _loc4_;
   if(this.outerThreshold < _loc3_)
   {
      this.crosshairMC.gotoAndStop("aim_far");
      this.aimSpeed = this.farAimSpeed;
      return undefined;
   }
   if(_loc3_ < this.innerThreshold)
   {
      this.shotTimer -= 2 + game.GetTime() % 4;
   }
   else if(_loc3_ < this.midThreshold)
   {
      this.crosshairMC.gotoAndStop("aim_near");
      this.aimSpeed = this.closeAimSpeed;
      this.shotTimer -= 1 + game.GetTime() % 2;
   }
   else
   {
      this.crosshairMC.gotoAndStop("aim_mid");
      this.aimSpeed = this.midAimSpeed;
      this.shotTimer -= 0.5;
   }
   if(this.shotTimer < 0)
   {
      this.shotTimer = this.shotRate;
      this.StartFiring();
   }
};
TurretObject.prototype.Update_PreFire = function()
{
   this.fireDelayTimer = this.fireDelayTimer + 1;
   if(this.prefireDelay <= this.fireDelayTimer)
   {
      if(!QueryRayObj(this.view,this.pos,player.pos,player))
      {
         this.StopFiring();
      }
      else
      {
         this.Fire();
      }
   }
};
TurretObject.prototype.Update_PostFire = function()
{
   this.fireDelayTimer = this.fireDelayTimer + 1;
   this.shotMC._alpha = 100 - 100 * (this.fireDelayTimer / this.postfireDelay);
   if(this.postfireDelay <= this.fireDelayTimer)
   {
      this.shotMC._visible = false;
      if(!QueryRayObj(this.view,this.pos,player.pos,player))
      {
         this.StopTargetting();
      }
      else
      {
         this.KeepTargetting();
      }
   }
};
