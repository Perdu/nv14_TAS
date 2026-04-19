DRONEWEAP_ZAP = 0;
DRONEWEAP_LASER = 1;
DRONEWEAP_CHAINGUN = 2;
DroneObject.prototype.TestVsPlayer = function(guy)
{
};
DroneObject.prototype.TestVsPlayer_Zap = function(guy)
{
   var _loc3_ = guy.pos;
   var _loc4_ = this.pos.x - _loc3_.x;
   var _loc5_ = this.pos.y - _loc3_.y;
   var _loc6_ = Math.sqrt(_loc4_ * _loc4_ + _loc5_ * _loc5_);
   if(_loc6_ < this.r + guy.r)
   {
      _loc4_ /= _loc6_;
      _loc5_ /= _loc6_;
      particles.SpawnZap(this.pos.x - _loc4_ * this.r,this.pos.y - _loc5_ * this.r,NormToRot(- _loc4_,- _loc5_));
      game.KillPlayer(KILLTYPE_ELECTRIC,(- _loc4_) * 10,(- _loc5_) * 10,_loc3_.x + guy.r * _loc4_,_loc3_.y + guy.r * _loc5_,this);
   }
};
DroneObject.prototype.TestVsRagParticle_Zap = function(guy)
{
   var _loc3_ = guy.pos;
   var _loc4_ = this.pos.x - _loc3_.x;
   var _loc5_ = this.pos.y - _loc3_.y;
   var _loc6_ = Math.sqrt(_loc4_ * _loc4_ + _loc5_ * _loc5_);
   if(_loc6_ < this.r + guy.xw)
   {
      _loc4_ /= _loc6_;
      _loc5_ /= _loc6_;
      particles.SpawnZap(this.pos.x - _loc4_ * this.r,this.pos.y - _loc5_ * this.r,NormToRot(- _loc4_,- _loc5_));
      player.RagDie(KILLTYPE_ELECTRIC);
      guy.ReportCollisionVsObject((- _loc4_) * 10,(- _loc5_) * 10,- _loc4_,- _loc5_,1);
   }
};
DroneObject.prototype.Think = function()
{
};
DroneObject.prototype.Think_TargetPlayer = function()
{
   trace("FRAME " + game.tickCounter + " Drone " + this.UID + " checking for player.");
   if (!_root.patch_options.recording) {
      var _loc2_ = gfx.CreateEmptySprite(LAYER_OBJECTS);
      _loc2_._x = this.pos.x;
      _loc2_._y = this.pos.y;
      _loc2_.clear();
      _loc2_.lineStyle(2,16711935,100);
      _loc2_.moveTo(0,0);
      _loc2_.lineTo(player.pos.x - this.pos.x,player.pos.y - this.pos.y);
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
   if(QueryRayObj(this.view,this.pos,player.pos,player))
   {
      trace("FRAME " + game.tickCounter + " Drone " + this.UID + " detected player.");
      this.StartFiring();
   }
};
DroneObject.prototype.StartMoving = function()
{
   objects.StartThink(this);
   this.Update = this.Update_Move;
   objects.StartDraw(this);
};
DroneObject.prototype.StartFiring_Laser = function()
{
   trace("FRAME " + game.tickCounter + " Drone " + this.UID + " firing laser.");
   this.mc.gotoAndPlay("laserdrone_prefire");
   objects.EndThink(this);
   objects.EndDraw(this);
   this.fireDelayTimer = 0;
   this.Update = this.Update_PreFire_Laser;
   if(!CollideRayvsTiles(this.targ,this.pos,this.view))
   {
   }
   this.targ2.x = this.targ.x - this.pos.x;
   this.targ2.y = this.targ.y - this.pos.y;
   this.laserLen = Math.sqrt(this.targ2.x * this.targ2.x + this.targ2.y * this.targ2.y);
   if(this.laserLen == 0)
   {
      this.StopFiring();
      return undefined;
   }
   this.beamMC._visible = true;
   this.beamMC.clear();
   this.beamMC.lineStyle(0,13334137,100);
   this.beamMC.moveTo(this.pos.x,this.pos.y);
   this.beamMC.lineTo(this.targ.x,this.targ.y);
   this.beamdx = this.targ2.x / this.laserLen;
   this.beamdy = this.targ2.y / this.laserLen;
};
DroneObject.prototype.StopFiring_Laser = function()
{
   this.snd.stop();
   this.mc.gotoAndPlay("laserdrone_postfire");
   this.beamMC._visible = false;
   this.blastMC._visible = false;
   this.blastMC.gotoAndStop(1);
   this.isFiring = false;
   this.fireDelayTimer = 0;
   this.Update = this.Update_PostFire_Laser;
};
DroneObject.prototype.Update_PreFire_Laser = function()
{
   particles.SpawnLaserCharge(this.pos);
   this.fireDelayTimer += 1;
   if(this.prefireDelay <= this.fireDelayTimer)
   {
      this.isFiring = true;
      this.Fire_Laser();
   }
};
DroneObject.prototype.Update_PostFire_Laser = function()
{
   this.fireDelayTimer += 1;
   if(this.postfireDelay <= this.fireDelayTimer)
   {
      this.StartMoving();
   }
};
DroneObject.prototype.Fire_Laser = function()
{
   this.mc.gotoAndStop("laserdrone_firing");
   this.beamMC.clear();
   this.beamMC.lineStyle(3,8921634,100);
   this.beamMC.moveTo(this.pos.x,this.pos.y);
   this.beamMC.lineTo(this.targ.x,this.targ.y);
   this.blastMC._x = this.targ.x;
   this.blastMC._y = this.targ.y;
   this.blastMC._visible = true;
   this.blastMC._xscale = this.blastMC._yscale = 0;
   this.blastMC.gotoAndPlay(1);
   this.laserLen *= this.laserLen;
   this.laserTimer = 0;
   this.Update = this.Update_FiringLaser;
};
DroneObject.prototype.Update_FiringLaser = function()
{
   particles.SpawnLaserCharge(this.pos);
   var _loc2_ = this.laserTimer / this.laserRate;
   this.blastMC._xscale = this.blastMC._yscale = 30 + 200 * _loc2_;
   var _loc3_ = player.pos.x - this.pos.x;
   var _loc4_ = player.pos.y - this.pos.y;
   var _loc5_ = _loc3_ * this.targ2.x + _loc4_ * this.targ2.y;
   _loc5_ /= this.laserLen;
   var _loc6_;
   var _loc7_;
   if(_loc5_ < 0)
   {
      _loc6_ = this.pos.x;
      _loc7_ = this.pos.y;
   }
   else if(_loc5_ < 1)
   {
      _loc6_ = this.pos.x + _loc5_ * this.targ2.x;
      _loc7_ = this.pos.y + _loc5_ * this.targ2.y;
   }
   else
   {
      _loc6_ = this.targ.x;
      _loc7_ = this.targ.y;
   }
   var _loc8_ = _loc6_ - player.pos.x;
   var _loc9_ = _loc7_ - player.pos.y;
   var _loc10_;
   if(Math.sqrt(_loc8_ * _loc8_ + _loc9_ * _loc9_) < player.r)
   {
      this.StopFiring_Laser();
      _loc10_ = Math.sqrt(this.targ2.x * this.targ2.x + this.targ2.y * this.targ2.y);
      game.KillPlayer(KILLTYPE_LASER,6 * (this.targ2.x / _loc10_),6 * (this.targ2.y / _loc10_),_loc6_,_loc7_,this);
      return undefined;
   }
   this.laserTimer += 1;
   if(this.laserRate <= this.laserTimer)
   {
      this.StopFiring();
      return undefined;
   }
};
DroneObject.prototype.StartFiring_Chaingun = function()
{
   this.mc.gotoAndPlay("chaingundrone_prefire");
   objects.EndThink(this);
   objects.EndDraw(this);
   this.fireDelayTimer = 0;
   this.Update = this.Update_PreFire;
};
DroneObject.prototype.StopFiring_Chaingun = function()
{
   this.snd.stop();
   this.mc.gotoAndPlay("chaingundrone_postfire");
   this.isFiring = false;
   this.fireDelayTimer = 0;
   this.Update = this.Update_PostFire_Chaingun;
};
DroneObject.prototype.Update_PreFire_Chaingun = function()
{
   var _loc2_ = player.pos.x - this.pos.x;
   var _loc3_ = player.pos.y - this.pos.y;
   var _loc4_ = NormToRot(_loc2_,_loc3_);
   if(180 < _loc4_)
   {
      _loc4_ -= 360;
   }
   var _loc5_ = _loc4_ - this.eyeMC._rotation;
   this.eyeMC._rotation += 0.1 * _loc5_;
   this.fireDelayTimer += 1;
   if(this.prefireDelay <= this.fireDelayTimer)
   {
      this.isFiring = true;
      this.Fire_Chaingun();
      this.mc.gotoAndPlay("chaingundrone_fire");
   }
};
DroneObject.prototype.Update_PostFire_Chaingun = function()
{
   this.fireDelayTimer += 1;
   if(this.postfireDelay <= this.fireDelayTimer)
   {
      this.StartMoving();
   }
};
DroneObject.prototype.Fire_Chaingun = function()
{
   this.chaingunTimer = 0;
   this.chaingunMaxNum = 4 + game.GetTime() % 5;
   this.chaingunSpread = 0.1 + 0.1 * (1 + game.GetTime() % 3);
   this.chaingunCurNum = 0;
   this.Update = this.Update_FiringChaingun;
   var _loc2_ = player.pos.x - this.pos.x;
   var _loc3_ = player.pos.y - this.pos.y;
   var _loc4_ = Math.sqrt(_loc2_ * _loc2_ + _loc3_ * _loc3_);
   if(_loc4_ == 0)
   {
      this.StopFiring();
      return undefined;
   }
   _loc2_ /= _loc4_;
   _loc3_ /= _loc4_;
   this.targ.x = _loc2_;
   this.targ.y = _loc3_;
   var _loc5_ = player.pos.x - player.oldpos.x;
   var _loc6_ = player.pos.y - player.oldpos.y;
   var _loc7_ = _loc5_ * (- _loc3_) + _loc6_ * _loc2_;
   if(_loc7_ < 0)
   {
      this.targ2.x = _loc3_;
      this.targ2.y = - _loc2_;
   }
   else
   {
      this.targ2.x = - _loc3_;
      this.targ2.y = _loc2_;
   }
};
DroneObject.prototype.Update_FiringChaingun = function()
{
   this.chaingunTimer += 1;
   var _loc2_;
   var _loc3_;
   var _loc4_;
   var _loc5_;
   var _loc6_;
   var _loc7_;
   var _loc8_;
   if(this.chaingunRate <= this.chaingunTimer)
   {
      this.chaingunTimer = 0;
      if(this.chaingunMaxNum < this.chaingunCurNum)
      {
         this.StopFiring_Chaingun();
         return undefined;
      }
      _loc2_ = this.chaingunCurNum / this.chaingunMaxNum - 0.5;
      _loc2_ *= this.chaingunSpread;
      _loc3_ = this.targ.x + _loc2_ * this.targ2.x;
      _loc4_ = this.targ.y + _loc2_ * this.targ2.y;
      this.targ3.x = this.pos.x + _loc3_;
      this.targ3.y = this.pos.y + _loc4_;
      if(QueryRayObj(this.view,this.pos,this.targ3,player))
      {
         this.StopFiring_Chaingun();
         game.KillPlayer(KILLTYPE_SOFTBULLET,_loc3_ * 5,_loc4_ * 5,this.view.x,this.view.y,this);
      }
      _loc5_ = this.view.x - this.pos.x;
      _loc6_ = this.view.y - this.pos.y;
      _loc7_ = Math.sqrt(_loc5_ * _loc5_ + _loc6_ * _loc6_);
      _loc5_ /= _loc7_;
      _loc6_ /= _loc7_;
      _loc8_ = NormToRot(_loc5_,_loc6_);
      particles.SpawnChainBullet(this.pos,this.view,_loc7_,_loc8_);
      this.eyeMC._rotation = _loc8_;
      this.chaingunCurNum += 1;
   }
};
