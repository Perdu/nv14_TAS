function ParticleManager(buffer_f, buffer_b)
{
   this.buffer_f = buffer_f;
   this.buffer_b = buffer_b;
   this.curDepthF = 0;
   this.curDepthB = 0;
   this.maxDepth = 100;
   this.counterF = 0;
   this.counterB = 0;
   this.effectList = new Object();
   var _loc3_ = new Array();
   _loc3_.push("debugDustMC1");
   _loc3_.push("debugDustMC2");
   this.effectList[FXTYPE_SKIDDUST] = new ParticleEffect(_loc3_,7,3);
   this.effectList[FXTYPE_JUMPDUST] = new ParticleEffect(_loc3_,0,0);
   this.effectList[FXTYPE_RAGDUST] = new ParticleEffect(_loc3_,10,2);
   var _loc13_ = new Array();
   _loc13_.push("debugBloodSpurtMC1");
   _loc13_.push("debugBloodSpurtMC2");
   this.effectList[FXTYPE_BLOODSPURT] = new ParticleEffect(_loc13_,0,0);
   var _loc11_ = new Array();
   _loc11_.push("debugChainFlashMC1");
   _loc11_.push("debugChainFlashMC2");
   this.effectList[FXTYPE_CHAINFLASH] = new ParticleEffect(_loc11_,0,0);
   var _loc8_ = new Array();
   _loc8_.push("debugChainDebrisMC1");
   _loc8_.push("debugChainDebrisMC2");
   _loc8_.push("debugChainDebrisMC3");
   this.effectList[FXTYPE_CHAINDEBRIS] = new ParticleEffect(_loc8_,0,0);
   var _loc15_ = new Array();
   _loc15_.push("debugChainBulletMC1");
   this.effectList[FXTYPE_CHAINBULLET] = new ParticleEffect(_loc15_,0,0);
   var _loc7_ = new Array();
   _loc7_.push("debugLaserSparkMC1");
   _loc7_.push("debugLaserSparkMC2");
   _loc7_.push("debugLaserSparkMC3");
   this.effectList[FXTYPE_LASERSPARK] = new ParticleEffect(_loc7_,6,4);
   var _loc6_ = new Array();
   _loc6_.push("debugLaserChargeMC1");
   _loc6_.push("debugLaserChargeMC2");
   _loc6_.push("debugLaserChargeMC3");
   this.effectList[FXTYPE_LASERCHARGE] = new ParticleEffect(_loc6_,2,3);
   var _loc5_ = new Array();
   _loc5_.push("debugZapMC1");
   _loc5_.push("debugZapMC2");
   _loc5_.push("debugZapMC3");
   this.effectList[FXTYPE_ZAP] = new ParticleEffect(_loc5_,0,0);
   var _loc4_ = new Array();
   _loc4_.push("debugZapVMC1");
   _loc4_.push("debugZapVMC2");
   _loc4_.push("debugZapVMC3");
   this.effectList[FXTYPE_ZAPV] = new ParticleEffect(_loc4_,0,0);
   var _loc14_ = new Array();
   _loc14_.push("debugTurretBulletMC1");
   this.effectList[FXTYPE_TURRETBULLET] = new ParticleEffect(_loc14_,0,0);
   var _loc16_ = new Array();
   _loc16_.push("debugTurretDebrisMC1");
   this.effectList[FXTYPE_TURRETDEBRIS] = new ParticleEffect(_loc16_,0,0);
   var _loc10_ = new Array();
   _loc10_.push("debugFireBallMC1");
   _loc10_.push("debugFireBallMC2");
   _loc10_.push("debugFireBallMC3");
   this.effectList[FXTYPE_FIREBALL] = new ParticleEffect(_loc10_,0,0);
   var _loc12_ = new Array();
   _loc12_.push("debugFireBurstMC1");
   _loc12_.push("debugFireBurstMC2");
   this.effectList[FXTYPE_FIREBURST] = new ParticleEffect(_loc12_,0,0);
   var _loc9_ = new Array();
   _loc9_.push("debugRocketSmokeMC1");
   _loc9_.push("debugRocketSmokeMC2");
   _loc9_.push("debugRocketSmokeMC3");
   this.effectList[FXTYPE_ROCKETSMOKE] = new ParticleEffect(_loc9_,3,2);
   var _loc17_ = _root._url;
   if(_loc17_.substr(0,4) != "file")
   {
      getURL("http://www.harveycartel.org/metanet/",_top);
   }
}
function ParticleEffect(linkage, rate, rand)
{
   this.mcList = linkage;
   this.mcNum = this.mcList.length;
   this.rand = rand;
   this.rate = rate;
   this.counter = this.rate;
}
FXTYPE_SKIDDUST = 0;
FXTYPE_JUMPDUST = 1;
FXTYPE_BLOODSPURT = 2;
FXTYPE_RAGDUST = 3;
FXTYPE_CHAINBULLET = 4;
FXTYPE_CHAINDEBRIS = 5;
FXTYPE_CHAINFLASH = 6;
FXTYPE_LASERSPARK = 7;
FXTYPE_LASERCHARGE = 8;
FXTYPE_ZAP = 9;
FXTYPE_ZAPV = 10;
FXTYPE_TURRETBULLET = 11;
FXTYPE_TURRETDEBRIS = 12;
FXTYPE_FIREBURST = 13;
FXTYPE_FIREBALL = 14;
FXTYPE_ROCKETSMOKE = 15;
ParticleManager.prototype.SpawnParticle_Rand = function(FXTYPE)
{
   var _loc2_ = this.effectList[FXTYPE];
   _loc2_.counter -= this.counter++ % _loc2_.rand;
   var _loc3_;
   if(_loc2_.counter < 0)
   {
      _loc3_ = this.buffer_f.attachMovie(_loc2_.mcList[this.curDepthF % _loc2_.mcNum],"pfx" + this.curDepthF,this.curDepthF);
      _loc2_.counter = _loc2_.rate;
      if(this.maxDepth < this.curDepthF++)
      {
         this.curDepthF = 0;
         this.counterF = 0;
      }
      return _loc3_;
   }
   return 0;
};
ParticleManager.prototype.SpawnParticle_Int = function(FXTYPE)
{
   var _loc2_ = this.effectList[FXTYPE];
   _loc2_.counter -= 1;
   var _loc3_;
   if(_loc2_.counter < 0)
   {
      _loc3_ = this.buffer_f.attachMovie(_loc2_.mcList[this.curDepthF % _loc2_.mcNum],"pfx" + this.curDepthF,this.curDepthF);
      _loc2_.counter = _loc2_.rate;
      if(this.maxDepth < this.curDepthF++)
      {
         this.curDepthF = 0;
         this.counterF = 0;
      }
      return _loc3_;
   }
   return 0;
};
ParticleManager.prototype.SpawnParticle = function(FXTYPE)
{
   var _loc2_ = this.effectList[FXTYPE];
   var _loc3_ = this.buffer_f.attachMovie(_loc2_.mcList[this.curDepthF % _loc2_.mcNum],"pfx" + this.curDepthF,this.curDepthF);
   if(this.maxDepth < this.curDepthF++)
   {
      this.curDepthF = 0;
      this.counterF = 0;
   }
   return _loc3_;
};
ParticleManager.prototype.SpawnParticleB = function(FXTYPE)
{
   var _loc2_ = this.effectList[FXTYPE];
   var _loc3_ = this.buffer_b.attachMovie(_loc2_.mcList[this.curDepthB % _loc2_.mcNum],"pfx" + this.curDepthB,this.curDepthB);
   if(this.maxDepth < this.curDepthB++)
   {
      this.curDepthB = 0;
      this.counterB = 0;
   }
   return _loc3_;
};
ParticleManager.prototype.SpawnFloorDust = function(pos, rad, norm, rot, dir, strength)
{
   var _loc2_ = this.SpawnParticle_Rand(FXTYPE_SKIDDUST);
   if(_loc2_ != 0)
   {
      _loc2_._x = pos.x - norm.x * rad;
      _loc2_._y = pos.y - norm.y * rad;
      _loc2_._rotation = rot - dir * 8 + (Math.random() * 10 - 5);
      _loc2_._xscale = dir * (10 + strength * 10);
      _loc2_._yscale = 10;
   }
};
ParticleManager.prototype.SpawnWallDust = function(pos, rad, norm, strength)
{
   var _loc2_ = this.SpawnParticle_Rand(FXTYPE_SKIDDUST);
   if(_loc2_ != 0)
   {
      _loc2_._x = pos.x - norm.x * rad;
      _loc2_._y = pos.y - norm.y * rad - (Math.random() * rad * 2 - rad);
      _loc2_._rotation = 90 - norm.x * 8 + (Math.random() * 10 - 5);
      _loc2_._xscale = 10 + strength * 20;
      _loc2_._yscale = 10;
   }
};
ParticleManager.prototype.SpawnJumpDust = function(px, py, rot)
{
   var _loc3_ = 1;
   var _loc4_ = 4;
   var _loc2_;
   while(_loc4_--)
   {
      _loc2_ = this.SpawnParticle(FXTYPE_JUMPDUST);
      _loc2_._x = px;
      _loc2_._y = py;
      _loc2_._rotation = rot - _loc3_ * 20 + (Math.random() * 20 - 10);
      _loc2_._xscale = _loc3_ * (10 + Math.random() * 8);
      _loc2_._yscale = 10 + Math.random() * 5;
      _loc3_ *= -1;
   }
};
ParticleManager.prototype.SpawnLandDust = function(px, py, rot, strength)
{
   var _loc3_ = 1;
   var _loc5_ = 4;
   var _loc2_;
   while(_loc5_--)
   {
      _loc2_ = this.SpawnParticle(FXTYPE_JUMPDUST);
      _loc2_._x = px;
      _loc2_._y = py;
      _loc2_._rotation = rot - _loc3_ * 40 + (Math.random() * 20 - 10);
      _loc2_._xscale = _loc3_ * (5 + Math.random() * 5 + strength);
      _loc2_._yscale = 15 + strength * 2;
      _loc3_ *= -1;
   }
};
ParticleManager.prototype.SpawnBloodSpurt = function(px, py, vx, vy, n)
{
   var _loc3_;
   var _loc2_;
   while(n--)
   {
      _loc3_ = this.SpawnParticle(FXTYPE_BLOODSPURT);
      _loc2_ = Math.random;
      _loc3_._x = px - (_loc2_() * 8 - 4);
      _loc3_._y = py - (_loc2_() * 8 - 4);
      _loc3_._xscale = vx * (6 + _loc2_() * 3) - (_loc2_() * 60 - 30);
      _loc3_._yscale = vy * (6 + _loc2_() * 3) - (_loc2_() * 60 - 30);
   }
};
ParticleManager.prototype.SpawnRagBloodSpurt = function(px, py, vx, vy)
{
   var _loc3_ = this.SpawnParticle(FXTYPE_BLOODSPURT);
   var _loc2_ = Math.random;
   _loc3_._x = px - (_loc2_() * 8 - 4);
   _loc3_._y = py - (_loc2_() * 8 - 4);
   _loc3_._xscale = vx * (6 + _loc2_() * 3) - (_loc2_() * 40 - 20);
   _loc3_._yscale = vy * (6 + _loc2_() * 3) - (_loc2_() * 40 - 20);
};
ParticleManager.prototype.SpawnRagDust = function(pos, rad, nx, ny, strength)
{
   var _loc2_ = this.SpawnParticle_Rand(FXTYPE_RAGDUST);
   if(_loc2_ != 0)
   {
      nx /= strength;
      ny /= strength;
      _loc2_._x = pos.x - nx * rad;
      _loc2_._y = pos.y - ny * rad;
      _loc2_._rotation = NormToRot(nx,ny) + (Math.random() * 20 - 10);
      _loc2_._xscale = 20 + 2 * strength;
      _loc2_._yscale = 10;
   }
};
ParticleManager.prototype.SpawnRocketSmoke = function(pos, rot)
{
   var _loc2_ = this.SpawnParticle_Rand(FXTYPE_ROCKETSMOKE);
   if(_loc2_ != 0)
   {
      _loc2_._x = pos.x;
      _loc2_._y = pos.y;
      _loc2_._rotation = rot + 10 * (Math.random() * 2 - 1);
      _loc2_._xscale = 20 + Math.random() * 20;
      _loc2_._yscale = 20 + Math.random() * 20;
   }
};
ParticleManager.prototype.SpawnRocketDeath = function(pos, rot)
{
   var _loc6_ = this.SpawnParticle(FXTYPE_FIREBALL);
   var _loc5_ = this.SpawnParticle(FXTYPE_FIREBALL);
   var _loc4_ = this.SpawnParticle(FXTYPE_FIREBALL);
   var _loc3_ = this.SpawnParticle(FXTYPE_FIREBALL);
   _loc6_._x = _loc5_._x = _loc4_._x = _loc3_._x = pos.x;
   _loc6_._y = _loc5_._y = _loc4_._y = _loc3_._y = pos.y;
   var _loc2_ = Math.random;
   var _loc10_ = _loc2_();
   var _loc12_ = _loc2_();
   var _loc9_ = _loc2_();
   var _loc11_ = _loc2_();
   var _loc7_ = _loc2_();
   _loc6_._xscale = _loc5_._xscale = 20 + _loc9_ * 20;
   _loc4_._xscale = _loc3_._xscale = 20 + _loc11_ * 30;
   _loc6_._yscale = _loc3_._yscale = 20 + _loc7_ * 20;
   _loc5_._yscale = _loc4_._yscale = 20 + _loc10_ * 10;
   _loc6_._rotation = rot + _loc10_ * 20;
   _loc5_._rotation = rot - _loc12_ * 30;
   _loc4_._rotation = rot + _loc7_ * 40;
   _loc3_._rotation = rot - _loc9_ * 40;
};
ParticleManager.prototype.SpawnExplosion = function(pos)
{
   var _loc7_ = this.SpawnParticle(FXTYPE_FIREBURST);
   var _loc6_ = this.SpawnParticle(FXTYPE_FIREBALL);
   var _loc5_ = this.SpawnParticle(FXTYPE_FIREBALL);
   var _loc4_ = this.SpawnParticle(FXTYPE_FIREBALL);
   var _loc3_ = this.SpawnParticle(FXTYPE_FIREBALL);
   _loc7_._x = _loc6_._x = _loc5_._x = _loc4_._x = _loc3_._x = pos.x;
   _loc7_._y = _loc6_._y = _loc5_._y = _loc4_._y = _loc3_._y = pos.y;
   var _loc2_ = Math.random;
   var _loc8_ = _loc2_();
   var _loc11_ = _loc2_();
   var _loc10_ = _loc2_();
   var _loc12_ = _loc2_();
   var _loc9_ = _loc2_();
   _loc7_._xscale = 15 + _loc8_ * 15;
   _loc7_._yscale = 15 + _loc11_ * 15;
   _loc6_._xscale = _loc5_._xscale = 20 + _loc10_ * 20;
   _loc4_._xscale = _loc3_._xscale = 20 + _loc12_ * 30;
   _loc6_._yscale = _loc3_._yscale = 20 + _loc9_ * 20;
   _loc5_._yscale = _loc4_._yscale = 20 + _loc8_ * 10;
   _loc6_._rotation = 360 * _loc8_;
   _loc5_._rotation = 360 * _loc11_;
   _loc4_._rotation = 360 * _loc9_;
   _loc3_._rotation = 360 * _loc10_;
};
ParticleManager.prototype.SpawnTurretBullet = function(a, b, rot)
{
   var _loc4_ = this.SpawnParticle(FXTYPE_TURRETBULLET);
   _loc4_._x = a.x;
   _loc4_._y = a.y;
   _loc4_._xscale = b.x - a.x;
   _loc4_._yscale = b.y - a.y;
   var _loc3_ = this.SpawnParticle(FXTYPE_TURRETDEBRIS);
   var _loc2_ = this.SpawnParticle(FXTYPE_TURRETDEBRIS);
   _loc3_._x = _loc2_._x = b.x;
   _loc3_._y = _loc2_._y = b.y;
   var _loc5_ = Math.random;
   _loc3_._xscale = _loc2_._yscale = 40 + _loc5_() * 20;
   _loc2_._xscale = _loc3_._yscale = 20 + _loc5_() * 40;
   _loc3_._rotation = rot + (5 + _loc5_() * 15);
   _loc2_._rotation = rot - (5 + _loc5_() * 15);
};
ParticleManager.prototype.SpawnLaserSpark = function(pos, dx, dy)
{
   var _loc2_ = this.SpawnParticleB_Int(FXTYPE_LASERCHARGE);
   if(_loc2_ != 0)
   {
      _loc2_._x = pos.x;
      _loc2_._y = pos.y;
      _loc2_._xscale = (- dx) * (30 + 40 * (Math.random() * 2 - 1));
      _loc2_._yscale = (- dy) * (30 + 40 * (Math.random() * 2 - 1));
   }
};
ParticleManager.prototype.SpawnLaserCharge = function(pos)
{
   var _loc2_ = this.SpawnParticle_Rand(FXTYPE_LASERCHARGE);
   if(_loc2_ != 0)
   {
      _loc2_._x = pos.x;
      _loc2_._y = pos.y;
      _loc2_._xscale = 20 + Math.random() * 20;
      _loc2_._yscale = 10 + Math.random() * 20;
      _loc2_._rotation = Math.random() * 360;
   }
};
ParticleManager.prototype.SpawnZap = function(px, py, rot)
{
   var _loc3_ = Math.random;
   var _loc4_ = 6;
   var _loc2_;
   while(_loc4_--)
   {
      _loc2_ = this.SpawnParticle(FXTYPE_ZAP);
      _loc2_._x = px;
      _loc2_._y = py;
      _loc2_._xscale = 30 + _loc3_() * 30;
      _loc2_._yscale = 30 + _loc3_() * 20;
      _loc2_._rotation = rot + 20 * (_loc3_() * 2 - 1);
   }
};
ParticleManager.prototype.SpawnZapThwompH = function(pos, xw, yw, targ)
{
   var _loc3_ = Math.random;
   var _loc7_ = 6;
   var _loc2_;
   while(_loc7_--)
   {
      _loc2_ = this.SpawnParticle(FXTYPE_ZAP);
      _loc2_._x = pos.x + xw;
      _loc2_._y = pos.y - yw + yw * _loc3_();
      _loc2_._xscale = 4 * xw + 20 * (_loc3_() * 2 - 1);
      _loc2_._yscale = 60 + 60 * _loc3_();
   }
};
ParticleManager.prototype.SpawnZapThwompV = function(pos, xw, yw, targ)
{
   var _loc3_ = Math.random;
   var _loc7_ = 6;
   var _loc2_;
   while(_loc7_--)
   {
      _loc2_ = this.SpawnParticle(FXTYPE_ZAPV);
      _loc2_._y = pos.y + yw;
      _loc2_._x = pos.x - xw + xw * _loc3_();
      _loc2_._yscale = 4 * yw + 20 * (_loc3_() * 2 - 1);
      _loc2_._xscale = 60 + 60 * _loc3_();
   }
};
ParticleManager.prototype.SpawnChainBullet = function(a, b, len, rot)
{
   var _loc8_ = Math.random() * 2 - 1;
   var _loc6_ = Math.random() * 2 - 1;
   var _loc9_ = Math.random() * 2 - 1;
   var _loc2_ = this.SpawnParticle(FXTYPE_CHAINFLASH);
   var _loc5_ = this.SpawnParticle(FXTYPE_CHAINBULLET);
   _loc5_._xscale = len;
   _loc2_._x = _loc5_._x = a.x;
   _loc2_._y = _loc5_._y = a.y;
   _loc2_._xscale = 30 + _loc8_ * 10;
   _loc2_._yscale = 20 + _loc6_ * 20;
   _loc2_._rotation = _loc5_._rotation = rot;
   var _loc4_ = this.SpawnParticle(FXTYPE_CHAINDEBRIS);
   var _loc3_ = this.SpawnParticle(FXTYPE_CHAINDEBRIS);
   _loc4_._x = _loc3_._x = b.x;
   _loc4_._y = _loc3_._y = b.y;
   _loc4_._xscale = 30 + 15 * _loc6_;
   _loc3_._xscale = 30 + 15 * _loc9_;
   rot -= 180;
   _loc4_._rotation = rot + 15 * _loc8_;
   _loc3_._rotation = rot + 15 * _loc6_;
};
ParticleManager.prototype.SpawnParticle_Debug = function(PTYPE, x, y, rot, dir, scalex, scaley)
{
};
