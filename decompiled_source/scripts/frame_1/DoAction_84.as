function RagParticle(x, y, w, d, snd)
{
   this.pos = new Vector2(x,y);
   this.oldpos = new Vector2(x,y);
   this.xw = w;
   this.yw = w;
   this.drag = d;
   this.nx = 0;
   this.ny = 0;
   this.hit = false;
   this.sndhit = false;
   this.v = 0;
   this.snd = snd;
}
function RagStick(p0, p1, w0, minratio, maxlen, linkage, scale, flip, col)
{
   this.p0 = p0;
   this.p1 = p1;
   this.w0 = w0;
   this.w1 = 1 - this.w0;
   this.minlen = maxlen * (scale / 100) * minratio;
   this.maxlen = maxlen * (scale / 100);
   this.curlen = this.maxlen;
   var _loc4_ = p0.x - p1.x;
   var _loc3_ = p0.y - p1.y;
   this.len = Math.sqrt(_loc4_ * _loc4_ + _loc3_ * _loc3_);
   this.mc = gfx.CreateSprite(linkage,LAYER_PLAYER);
   this.mc._xscale = scale;
   this.mc._yscale = scale;
   this.flip = flip;
   this.mc._visible = false;
   var _loc5_;
   if(col != 0)
   {
      _loc5_ = new Color(this.mc);
      _loc5_.setRGB(col);
   }
}
function Ragdoll(pos, rad, scale, col)
{
   this.snd = gfx.CreateSprite("ragdollSoundMC",LAYER_PLAYER);
   this.pList = new Object();
   this.pList.b0 = new RagParticle(pos.x,pos.y,2.5,0.99,this.snd);
   this.pList.b1 = new RagParticle(pos.x,pos.y - rad,2.5,0.995,this.snd);
   this.pList.h0 = new RagParticle(pos.x + rad,pos.y - rad,2,0.995,this.snd);
   this.pList.h1 = new RagParticle(pos.x - rad,pos.y - rad,2,0.99,this.snd);
   this.pList.f0 = new RagParticle(pos.x + rad,pos.y + rad,3,0.99,this.snd);
   this.pList.f1 = new RagParticle(pos.x - rad,pos.y + rad,3,0.995,this.snd);
   this.sList = new Object();
   this.sList.armL = new RagStick(this.pList.b1.pos,this.pList.h1.pos,0.26,0.6,40,"arm_m",scale,-1,col);
   this.sList.legL = new RagStick(this.pList.b0.pos,this.pList.f1.pos,0.37,0.6,60,"leg_m",scale,1,col);
   this.sList.body = new RagStick(this.pList.b0.pos,this.pList.b1.pos,0.4,0.8,30,"body_m",scale,1,col);
   this.sList.legR = new RagStick(this.pList.b0.pos,this.pList.f0.pos,0.32,0.6,60,"leg_m",scale,1,col);
   this.sList.armR = new RagStick(this.pList.b1.pos,this.pList.h0.pos,0.2,0.6,40,"arm_m",scale,-1,col);
   this.pList.b0.otherP = this.pList.b1;
   this.pList.b1.otherP = this.pList.b0;
   this.pList.h0.otherP = this.pList.h1;
   this.pList.h1.otherP = this.pList.h0;
   this.pList.f0.otherP = this.pList.f1;
   this.pList.f1.otherP = this.pList.f0;
   this.exploded = false;
}
function CollideRagParticleVsObjects(p)
{
   var _loc3_ = tiles.GetTile_V(p.pos);
   var _loc1_ = _loc3_.next;
   while(_loc1_ != null)
   {
      _loc1_.TestVsRagParticle(p);
      _loc1_ = _loc1_.next;
   }
   _loc1_ = _loc3_.nD.next;
   while(_loc1_ != null)
   {
      _loc1_.TestVsRagParticle(p);
      _loc1_ = _loc1_.next;
   }
   _loc1_ = _loc3_.nD.nR.next;
   while(_loc1_ != null)
   {
      _loc1_.TestVsRagParticle(p);
      _loc1_ = _loc1_.next;
   }
   _loc1_ = _loc3_.nD.nL.next;
   while(_loc1_ != null)
   {
      _loc1_.TestVsRagParticle(p);
      _loc1_ = _loc1_.next;
   }
   _loc1_ = _loc3_.nL.next;
   while(_loc1_ != null)
   {
      _loc1_.TestVsRagParticle(p);
      _loc1_ = _loc1_.next;
   }
   _loc1_ = _loc3_.nL.nU.next;
   while(_loc1_ != null)
   {
      _loc1_.TestVsRagParticle(p);
      _loc1_ = _loc1_.next;
   }
   _loc1_ = _loc3_.nR.next;
   while(_loc1_ != null)
   {
      _loc1_.TestVsRagParticle(p);
      _loc1_ = _loc1_.next;
   }
   _loc1_ = _loc3_.nR.nU.next;
   while(_loc1_ != null)
   {
      _loc1_.TestVsRagParticle(p);
      _loc1_ = _loc1_.next;
   }
   _loc1_ = _loc3_.nU.next;
   while(_loc1_ != null)
   {
      _loc1_.TestVsRagParticle(p);
      _loc1_ = _loc1_.next;
   }
}
RagParticle.prototype.ReportCollisionVsWorld = function(x, y, nx, ny, t)
{
   var _loc2_ = this.pos;
   var _loc7_ = this.oldpos;
   var _loc12_ = _loc2_.x - _loc7_.x;
   var _loc10_ = _loc2_.y - _loc7_.y;
   var _loc5_ = _loc12_ * nx + _loc10_ * ny;
   var _loc4_ = _loc5_ * nx;
   var _loc3_ = _loc5_ * ny;
   var _loc9_ = _loc12_ - _loc4_;
   var _loc8_ = _loc10_ - _loc3_;
   var _loc13_;
   var _loc6_;
   var _loc11_;
   if(_loc5_ < 0)
   {
      if(_loc5_ < -3)
      {
         particles.SpawnRagBloodSpurt(_loc2_.x,_loc2_.y,- _loc4_,- _loc3_);
         _loc13_ = Math.random();
         _loc6_ = 0;
         if(_loc13_ < 0.33)
         {
            _loc6_ = 1;
         }
         else if(_loc13_ < 0.66)
         {
            _loc6_ = 2;
         }
         if(_loc6_ == 0)
         {
            this.snd.gotoAndPlay("hard1");
         }
         else if(_loc6_ == 1)
         {
            this.snd.gotoAndPlay("hard2");
         }
         else if(_loc6_ == 2)
         {
            this.snd.gotoAndPlay("hard3");
         }
      }
      else
      {
         if(_loc5_ < -2)
         {
            if(Math.random() < 0.5)
            {
               this.snd.gotoAndPlay("med1");
            }
            else
            {
               this.snd.gotoAndPlay("med2");
            }
         }
         else if(_loc5_ < -1.2)
         {
            if(Math.random() < 0.5)
            {
               this.snd.gotoAndPlay("soft1");
            }
            else
            {
               this.snd.gotoAndPlay("soft2");
            }
         }
         _loc11_ = _loc9_ * _loc9_ + _loc8_ * _loc8_;
         if(0.3 < _loc11_)
         {
            particles.SpawnRagDust(this.pos,this.xw,_loc9_,_loc8_,_loc11_);
         }
      }
      _loc4_ *= 1.4;
      _loc3_ *= 1.4;
   }
   else
   {
      _loc4_ = _loc3_ = 0;
   }
   _loc2_.x += x;
   _loc2_.y += y;
   _loc7_.x += x + _loc4_ + _loc9_ * 0.15;
   _loc7_.y += y + _loc3_ + _loc8_ * 0.15;
   this.nx = nx;
   this.ny = ny;
   this.hit = true;
};
RagParticle.prototype.ReportCollisionVsObject = function(px, py, nx, ny, bias)
{
   var _loc3_ = px;
   var _loc2_ = py;
   var _loc9_;
   var _loc5_;
   var _loc4_;
   var _loc8_;
   var _loc19_;
   if(this.hit)
   {
      _loc9_ = Math.sqrt(_loc3_ * _loc3_ + _loc2_ * _loc2_);
      _loc5_ = this.nx;
      _loc4_ = this.ny;
      _loc8_ = _loc5_ * px + _loc4_ * _loc2_;
      if(_loc8_ < 0)
      {
         _loc19_ = (- _loc4_) * _loc3_ + _loc5_ * _loc2_;
         _loc9_ *= 0.1;
         if(_loc19_ < 0)
         {
            _loc3_ = _loc9_ * (_loc4_ + _loc5_);
            _loc2_ = _loc9_ * (- _loc5_ + _loc4_);
         }
         else
         {
            _loc3_ = _loc9_ * (- _loc4_ + _loc5_);
            _loc2_ = _loc9_ * (_loc5_ + _loc4_);
         }
      }
   }
   var _loc11_ = this.pos;
   var _loc13_ = this.oldpos;
   var _loc17_ = _loc11_.x - _loc13_.x;
   var _loc15_ = _loc11_.y - _loc13_.y;
   _loc8_ = _loc17_ * nx + _loc15_ * ny;
   var _loc7_ = _loc8_ * nx;
   var _loc6_ = _loc8_ * ny;
   px = _loc17_ - _loc7_;
   py = _loc15_ - _loc6_;
   var _loc18_;
   var _loc10_;
   var _loc16_;
   if(_loc8_ < 0)
   {
      if(_loc8_ < -3)
      {
         particles.SpawnRagBloodSpurt(_loc11_.x,_loc11_.y,- _loc7_,- _loc6_);
         _loc18_ = Math.random();
         _loc10_ = 0;
         if(_loc18_ < 0.33)
         {
            _loc10_ = 1;
         }
         else if(_loc18_ < 0.66)
         {
            _loc10_ = 2;
         }
         if(_loc10_ == 0)
         {
            this.snd.gotoAndPlay("hard1");
         }
         else if(_loc10_ == 1)
         {
            this.snd.gotoAndPlay("hard2");
         }
         else if(_loc10_ == 2)
         {
            this.snd.gotoAndPlay("hard3");
         }
      }
      else
      {
         if(_loc8_ < -2)
         {
            _loc18_ = Math.rnd < 0.5;
            if(_loc18_ == false)
            {
               this.snd.gotoAndPlay("med1");
            }
            else
            {
               this.snd.gotoAndPlay("med2");
            }
         }
         else if(_loc8_ < -1)
         {
            _loc18_ = Math.rnd < 0.5;
            if(_loc18_ == false)
            {
               this.snd.gotoAndPlay("soft1");
            }
            else
            {
               this.snd.gotoAndPlay("soft2");
            }
         }
         _loc16_ = px * px + py * py;
         if(0.3 < _loc16_)
         {
            particles.SpawnRagDust(this.pos,this.xw,px,py,_loc16_);
         }
      }
      _loc7_ *= 1.4;
      _loc6_ *= 1.4;
   }
   else
   {
      _loc7_ = _loc6_ = 0;
   }
   _loc13_.x += _loc3_ + _loc7_ + px * 0.15;
   _loc13_.y += _loc2_ + _loc6_ + py * 0.15;
   player.raggy.PropagateForce(_loc3_,_loc2_,this,bias);
};
Ragdoll.prototype.Destruct = function()
{
   var _loc2_;
   for(var _loc3_ in this.sList)
   {
      _loc2_ = this.sList[_loc3_];
      DestroyMC(_loc2_.mc);
      delete _loc2_.mc;
   }
};
Ragdoll.prototype.Hide = function()
{
   var _loc2_ = this.sList;
   for(var _loc3_ in _loc2_)
   {
      _loc2_.mc._visible = false;
   }
};
Ragdoll.prototype.Tick = function()
{
   var _loc8_ = this.pList;
   var _loc2_;
   var _loc18_;
   var _loc27_;
   var _loc26_;
   var _loc0_;
   var _loc25_;
   var _loc24_;
   var _loc10_;
   var _loc9_;
   var _loc21_;
   for(var _loc29_ in _loc8_)
   {
      _loc2_ = _loc8_[_loc29_].pos;
      _loc18_ = _loc8_[_loc29_].oldpos;
      _loc27_ = _loc18_.x;
      _loc26_ = _loc18_.y;
      _loc25_ = _loc18_.x = _loc2_.x;
      _loc24_ = _loc18_.y = _loc2_.y;
      _loc10_ = _loc25_ - _loc27_;
      _loc9_ = _loc24_ - _loc26_;
      _loc21_ = _loc8_[_loc29_].drag;
      _loc2_.x += _loc21_ * _loc10_;
      _loc2_.y += _loc21_ * _loc9_ + 0.15;
      _loc8_[_loc29_].v = _loc10_ * _loc10_ + _loc9_ * _loc9_;
   }
   var _loc28_ = this.sList;
   var _loc4_;
   var _loc20_;
   var _loc19_;
   var _loc22_;
   var _loc23_;
   var _loc17_;
   var _loc15_;
   var _loc3_;
   var _loc7_;
   var _loc13_;
   for(_loc29_ in _loc28_)
   {
      _loc4_ = _loc28_[_loc29_];
      _loc20_ = _loc4_.p0;
      _loc19_ = _loc4_.p1;
      _loc22_ = _loc4_.minlen;
      _loc23_ = _loc4_.maxlen;
      _loc17_ = _loc20_.x - _loc19_.x;
      _loc15_ = _loc20_.y - _loc19_.y;
      _loc3_ = Math.sqrt(_loc17_ * _loc17_ + _loc15_ * _loc15_);
      _loc7_ = 0;
      _loc13_ = 0;
      if(_loc3_ != 0)
      {
         if(_loc3_ < _loc22_)
         {
            _loc7_ = _loc13_ = (_loc3_ - _loc22_) / _loc3_;
         }
         else
         {
            if(_loc23_ >= _loc3_)
            {
               _loc4_.curlen = _loc3_;
               continue;
            }
            _loc7_ = _loc13_ = (_loc3_ - _loc23_) / _loc3_;
         }
         _loc4_.curlen = _loc3_ - _loc7_;
         _loc7_ *= _loc4_.w0;
         _loc13_ *= _loc4_.w1;
         _loc20_.x -= _loc17_ * _loc7_;
         _loc20_.y -= _loc15_ * _loc7_;
         _loc19_.x += _loc17_ * _loc13_;
         _loc19_.y += _loc15_ * _loc13_;
      }
   }
   var _loc6_;
   var _loc5_;
   var _loc12_;
   var _loc11_;
   var _loc16_;
   var _loc14_;
   for(_loc29_ in _loc8_)
   {
      _loc2_ = _loc8_[_loc29_];
      if(_loc2_.v < 2)
      {
         CollideAABBvsTileMap(_loc2_);
      }
      else if(_loc2_.v < 3)
      {
         _loc6_ = _loc2_.pos.x;
         _loc5_ = _loc2_.pos.y;
         _loc2_.hit = false;
         CollideAABBvsTileMap(_loc2_);
         if(_loc2_.hit)
         {
            _loc12_ = 0.5 * (_loc6_ + _loc2_.oldpos.x);
            _loc11_ = 0.5 * (_loc5_ + _loc2_.oldpos.y);
            _loc10_ = _loc6_ - _loc12_;
            _loc9_ = _loc5_ - _loc11_;
            _loc2_.oldpos.x -= _loc10_;
            _loc2_.oldpos.y -= _loc9_;
            _loc2_.pos.x = _loc12_;
            _loc2_.pos.y = _loc11_;
            _loc2_.hit = false;
            CollideAABBvsTileMap(_loc2_);
            if(!_loc2_.hit)
            {
               _loc2_.pos.x = _loc6_;
               _loc2_.pos.y = _loc5_;
               _loc2_.oldpos.x += _loc10_;
               _loc2_.oldpos.y += _loc9_;
            }
         }
      }
      else
      {
         _loc6_ = _loc2_.pos.x;
         _loc5_ = _loc2_.pos.y;
         _loc16_ = 0.3333333333333333;
         _loc14_ = 0.6666666666666666;
         _loc2_.hit = false;
         CollideAABBvsTileMap(_loc2_);
         if(_loc2_.hit)
         {
            _loc12_ = _loc14_ * _loc6_ + _loc16_ * _loc2_.oldpos.x;
            _loc11_ = _loc14_ * _loc5_ + _loc16_ * _loc2_.oldpos.y;
            _loc6_ = _loc2_.pos.x;
            _loc5_ = _loc2_.pos.y;
            _loc10_ = _loc6_ - _loc12_;
            _loc9_ = _loc5_ - _loc11_;
            _loc2_.oldpos.x -= _loc10_;
            _loc2_.oldpos.y -= _loc9_;
            _loc2_.pos.x = _loc12_;
            _loc2_.pos.y = _loc11_;
            _loc2_.hit = false;
            CollideAABBvsTileMap(_loc2_);
            if(_loc2_.hit)
            {
               _loc12_ = _loc16_ * _loc6_ + _loc14_ * _loc2_.oldpos.x;
               _loc11_ = _loc16_ * _loc5_ + _loc14_ * _loc2_.oldpos.y;
               _loc6_ = _loc2_.pos.x;
               _loc5_ = _loc2_.pos.y;
               _loc10_ = _loc6_ - _loc12_;
               _loc9_ = _loc5_ - _loc11_;
               _loc2_.oldpos.x -= _loc10_;
               _loc2_.oldpos.y -= _loc9_;
               _loc2_.pos.x = _loc12_;
               _loc2_.pos.y = _loc11_;
               _loc2_.hit = false;
               CollideAABBvsTileMap(_loc2_);
               if(!_loc2_.hit)
               {
                  _loc2_.pos.x = _loc6_;
                  _loc2_.pos.y = _loc5_;
                  _loc2_.oldpos.x += _loc10_;
                  _loc2_.oldpos.y += _loc9_;
               }
            }
            else
            {
               _loc2_.pos.x = _loc6_;
               _loc2_.pos.y = _loc5_;
               _loc2_.oldpos.x += _loc10_;
               _loc2_.oldpos.y += _loc9_;
            }
         }
      }
      CollideRagParticleVsObjects(_loc2_);
   }
};
Ragdoll.prototype.PropagateForce = function(x, y, part, bias)
{
   var _loc7_;
   var _loc3_;
   var _loc2_;
   var _loc8_;
   var _loc9_;
   var _loc10_;
   var _loc4_;
   if(this.exploded)
   {
      part.pos.x += 1.5 * x;
      part.pos.y += 1.5 * y;
      part.otherP.pos.x += x;
      part.otherP.pos.y += y;
   }
   else
   {
      _loc7_ = Math.sqrt(x * x + y * y);
      _loc7_ *= 0.1;
      _loc3_ = part.nx;
      _loc2_ = part.ny;
      _loc8_ = _loc3_ * px + _loc2_ * y;
      if(_loc8_ < 0)
      {
         _loc9_ = (- _loc2_) * x + _loc3_ * y;
         if(_loc9_ < 0)
         {
            x = _loc7_ * (_loc2_ + _loc3_);
            y = _loc7_ * (- _loc3_ + _loc2_);
         }
         else
         {
            x = _loc7_ * (- _loc2_ + _loc3_);
            y = _loc7_ * (_loc3_ + _loc2_);
         }
      }
      part.pos.x += x;
      part.pos.y += y;
      x *= bias;
      y *= bias;
      _loc10_ = this.pList;
      for(var _loc12_ in _loc10_)
      {
         _loc4_ = _loc10_[_loc12_];
         if(_loc4_.hit)
         {
            _loc3_ = _loc4_.nx;
            _loc2_ = _loc4_.ny;
            _loc8_ = _loc3_ * px + _loc2_ * y;
            if(_loc8_ < 0)
            {
               _loc9_ = (- _loc2_) * x + _loc3_ * y;
               if(_loc9_ < 0)
               {
                  x = _loc7_ * (_loc2_ + _loc3_);
                  y = _loc7_ * (- _loc3_ + _loc2_);
               }
               else
               {
                  x = _loc7_ * (- _loc2_ + _loc3_);
                  y = _loc7_ * (_loc3_ + _loc2_);
               }
            }
         }
         _loc4_.pos.x += x;
         _loc4_.pos.y += y;
      }
   }
};
Ragdoll.prototype.Explode = function()
{
   var _loc3_ = this.pList;
   var _loc2_ = this.sList;
   var _loc5_ = _loc3_.b1;
   var _loc11_ = new RagParticle(_loc5_.pos.x,_loc5_.pos.y,_loc5_.xw,_loc5_.drag);
   var _loc10_ = new RagParticle(_loc5_.pos.x,_loc5_.pos.y,_loc5_.xw,_loc5_.drag);
   _loc2_.armL.p0 = _loc11_.pos;
   _loc2_.armR.p0 = _loc10_.pos;
   var _loc6_ = _loc3_.b0;
   var _loc9_ = new RagParticle(_loc6_.pos.x,_loc6_.pos.y,_loc6_.xw,_loc6_.drag);
   var _loc8_ = new RagParticle(_loc6_.pos.x,_loc6_.pos.y,_loc6_.xw,_loc6_.drag);
   _loc2_.legL.p0 = _loc9_.pos;
   _loc2_.legR.p0 = _loc8_.pos;
   _loc3_.t0 = _loc11_;
   _loc3_.t1 = _loc10_;
   _loc3_.t2 = _loc9_;
   _loc3_.t3 = _loc8_;
   _loc11_.otherP = _loc3_.h1;
   _loc3_.h1.otherP = _loc11_;
   _loc10_.otherP = _loc3_.h0;
   _loc3_.h0.otherP = _loc10_;
   _loc9_.otherP = _loc3_.f1;
   _loc3_.f1.otherP = _loc9_;
   _loc8_.otherP = _loc3_.f0;
   _loc3_.f0.otherP = _loc8_;
   var _loc12_ = 8;
   var _loc4_ = _loc12_ * 0.5;
   var _loc22_ = _loc12_ * 0.25;
   var _loc7_ = Math.random;
   var _loc21_ = _loc7_() * _loc12_ - _loc4_;
   var _loc20_ = _loc7_() * _loc12_ - _loc4_;
   var _loc19_ = _loc7_() * _loc12_ - _loc4_;
   var _loc18_ = _loc7_() * _loc12_ - _loc4_;
   var _loc17_ = _loc7_() * _loc4_ + _loc4_;
   var _loc16_ = _loc7_() * _loc4_ + _loc4_;
   var _loc15_ = _loc7_() * _loc4_ + _loc4_;
   var _loc14_ = _loc7_() * _loc4_ + _loc4_;
   _loc11_.oldpos.x -= _loc21_;
   _loc10_.oldpos.x -= _loc20_;
   _loc9_.oldpos.x -= _loc19_;
   _loc8_.oldpos.x -= _loc18_;
   _loc11_.oldpos.y += _loc17_;
   _loc10_.oldpos.y += _loc16_;
   _loc9_.oldpos.y += _loc15_;
   _loc8_.oldpos.y += _loc14_;
   this.exploded = true;
   particles.SpawnBloodSpurt(_loc11_.pos.x,_loc11_.pos.y,_loc21_,_loc17_,3);
   particles.SpawnBloodSpurt(_loc10_.pos.x,_loc10_.pos.y,_loc20_,_loc16_,3);
   particles.SpawnBloodSpurt(_loc9_.pos.x,_loc9_.pos.y,_loc19_,_loc15_,3);
   particles.SpawnBloodSpurt(_loc8_.pos.x,_loc8_.pos.y,_loc18_,_loc14_,3);
   _loc2_ = this.sList;
   for(var _loc13_ in _loc2_)
   {
      _loc2_[_loc13_].w0 = _loc2_[_loc13_].w1 = 0.5;
   }
};
Ragdoll.prototype.UnExplode = function()
{
   var _loc2_ = this.pList;
   var _loc3_ = this.sList;
   _loc3_.armL.p0 = _loc2_.b1.pos;
   _loc3_.armR.p0 = _loc2_.b1.pos;
   _loc3_.legL.p0 = _loc2_.b0.pos;
   _loc3_.legR.p0 = _loc2_.b0.pos;
   delete _loc2_.t0;
   delete _loc2_.t1;
   delete _loc2_.t2;
   delete _loc2_.t3;
   this.exploded = false;
};
Ragdoll.prototype.Activate = function()
{
   this.chunkAccumulator = 0;
   var _loc2_ = this.sList;
   for(var _loc3_ in _loc2_)
   {
      temp = _loc2_[_loc3_].mc;
      temp._visible = true;
   }
};
Ragdoll.prototype.Deactivate = function()
{
   var _loc2_ = this.sList;
   for(var _loc3_ in _loc2_)
   {
      temp = _loc2_[_loc3_].mc;
      temp._visible = false;
   }
};
Ragdoll.prototype.MimicMC = function(vx, vy, mc, facing, prevframe)
{
   var _loc4_ = this.sList;
   var _loc7_;
   if(facing < 0)
   {
      _loc7_ = 1;
   }
   else
   {
      _loc7_ = -1;
   }
   var _loc5_;
   for(var _loc14_ in _loc4_)
   {
      _loc5_ = _loc4_[_loc14_].mc;
      _loc5_._yscale = _loc4_[_loc14_].flip * _loc7_ * Math.abs(_loc5_._yscale);
   }
   var _loc2_ = new Object();
   var _loc6_ = this.pList;
   var _loc13_ = _loc6_.b0;
   var _loc12_ = _loc6_.b1;
   var _loc11_ = _loc6_.h0;
   var _loc10_ = _loc6_.h1;
   var _loc16_ = _loc6_.f0;
   var _loc15_ = _loc6_.f1;
   _loc2_.x = mc.shoulder._x;
   _loc2_.y = mc.shoulder._y;
   mc.localToGlobal(_loc2_);
   _loc12_.pos.x = _loc2_.x;
   _loc12_.pos.y = _loc2_.y;
   _loc2_.x = mc.pelvis._x;
   _loc2_.y = mc.pelvis._y;
   mc.localToGlobal(_loc2_);
   _loc13_.pos.x = _loc2_.x;
   _loc13_.pos.y = _loc2_.y;
   _loc2_.x = mc.handR._x;
   _loc2_.y = mc.handR._y;
   mc.localToGlobal(_loc2_);
   _loc11_.pos.x = _loc2_.x;
   _loc11_.pos.y = _loc2_.y;
   _loc2_.x = mc.handL._x;
   _loc2_.y = mc.handL._y;
   mc.localToGlobal(_loc2_);
   _loc10_.pos.x = _loc2_.x;
   _loc10_.pos.y = _loc2_.y;
   _loc2_.x = mc.footR._x;
   _loc2_.y = mc.footR._y;
   mc.localToGlobal(_loc2_);
   _loc16_.pos.x = _loc2_.x;
   _loc16_.pos.y = _loc2_.y;
   _loc2_.x = mc.footL._x;
   _loc2_.y = mc.footL._y;
   mc.localToGlobal(_loc2_);
   _loc15_.pos.x = _loc2_.x;
   _loc15_.pos.y = _loc2_.y;
   mc.gotoAndStop(prevframe);
   _loc2_.x = mc.shoulder._x;
   _loc2_.y = mc.shoulder._y;
   mc.localToGlobal(_loc2_);
   _loc12_.oldpos.x = _loc2_.x - vx;
   _loc12_.oldpos.y = _loc2_.y - vy;
   _loc2_.x = mc.pelvis._x;
   _loc2_.y = mc.pelvis._y;
   mc.localToGlobal(_loc2_);
   _loc13_.oldpos.x = _loc2_.x - vx;
   _loc13_.oldpos.y = _loc2_.y - vy;
   _loc2_.x = mc.handR._x;
   _loc2_.y = mc.handR._y;
   mc.localToGlobal(_loc2_);
   _loc11_.oldpos.x = _loc2_.x - vx;
   _loc11_.oldpos.y = _loc2_.y - vy;
   _loc2_.x = mc.handL._x;
   _loc2_.y = mc.handL._y;
   mc.localToGlobal(_loc2_);
   _loc10_.oldpos.x = _loc2_.x - vx;
   _loc10_.oldpos.y = _loc2_.y - vy;
   _loc2_.x = mc.footR._x;
   _loc2_.y = mc.footR._y;
   mc.localToGlobal(_loc2_);
   _loc16_.oldpos.x = _loc2_.x - vx;
   _loc16_.oldpos.y = _loc2_.y - vy;
   _loc2_.x = mc.footL._x;
   _loc2_.y = mc.footL._y;
   mc.localToGlobal(_loc2_);
   _loc15_.oldpos.x = _loc2_.x - vx;
   _loc15_.oldpos.y = _loc2_.y - vy;
};
Ragdoll.prototype.Shove = function(x, y)
{
   for(var _loc2_ in this.pList)
   {
      this.pList[_loc2_].oldpos.x -= x * (Math.random() + 0.4);
      this.pList[_loc2_].oldpos.y -= y * (Math.random() + 0.4);
   }
};
Ragdoll.prototype.Shove_VertBias = function(fx, fy, px, py, midy, rad)
{
   var _loc9_ = this.pList;
   var _loc19_ = _loc9_.b0;
   var _loc17_ = _loc9_.b1;
   var _loc15_ = _loc9_.h0;
   var _loc14_ = _loc9_.h1;
   var _loc21_ = _loc9_.f0;
   var _loc20_ = _loc9_.f1;
   var _loc3_ = (py - midy) / rad;
   var _loc8_ = 0.8;
   var _loc5_ = 0.4;
   var _loc12_ = 0.2;
   var _loc7_ = 1;
   var _loc4_ = 1;
   var _loc6_ = 1;
   var _loc13_;
   if(_loc3_ < 0)
   {
      if(_loc3_ < -1)
      {
         _loc7_ = _loc5_;
         _loc4_ = _loc8_;
         _loc6_ = _loc12_;
      }
      else
      {
         _loc3_ *= -1;
         _loc13_ = 1 - _loc3_;
         _loc7_ = _loc13_ * _loc8_ + _loc3_ * _loc5_;
         _loc4_ = _loc13_ * _loc5_ + _loc3_ * _loc8_;
         _loc6_ = _loc13_ * _loc5_ + _loc3_ * _loc12_;
      }
   }
   else if(0 < _loc3_)
   {
      if(1 < _loc3_)
      {
         _loc7_ = _loc5_;
         _loc6_ = _loc8_;
         _loc4_ = _loc12_;
      }
      else
      {
         _loc13_ = 1 - _loc3_;
         _loc7_ = _loc13_ * _loc8_ + _loc3_ * _loc5_;
         _loc6_ = _loc13_ * _loc5_ + _loc3_ * _loc8_;
         _loc4_ = _loc13_ * _loc5_ + _loc3_ * _loc12_;
      }
   }
   else
   {
      _loc4_ = 0.4;
      _loc7_ = 0.4;
      _loc6_ = 0.4;
   }
   var _loc2_ = Math.random;
   _loc19_.oldpos.x -= (_loc2_() + _loc7_) * fx;
   _loc19_.oldpos.y -= (_loc2_() + _loc7_) * fy;
   _loc17_.oldpos.x -= (_loc2_() + _loc4_) * fx;
   _loc17_.oldpos.y -= (_loc2_() + _loc4_) * fy;
   var _loc18_ = _loc6_ * (0.8 + 0.2 * _loc2_());
   var _loc16_ = _loc6_ * (0.9 + 0.1 * _loc2_());
   _loc21_.oldpos.x -= (_loc2_() + _loc18_) * fx;
   _loc21_.oldpos.y -= (_loc2_() + _loc18_) * fy;
   _loc20_.oldpos.x -= (_loc2_() + _loc16_) * fx;
   _loc20_.oldpos.y -= (_loc2_() + _loc16_) * fy;
   var _loc23_ = _loc4_ * (0.9 + 0.1 * _loc2_());
   var _loc22_ = _loc4_ * (0.8 + 0.2 * _loc2_());
   _loc15_.oldpos.x -= (_loc2_() + _loc23_) * fx;
   _loc15_.oldpos.y -= (_loc2_() + _loc23_) * fy;
   _loc14_.oldpos.x -= (_loc2_() + _loc22_) * fx;
   _loc14_.oldpos.y -= (_loc2_() + _loc22_) * fy;
};
Ragdoll.prototype.DrawDebug = function()
{
   static_rend.SetStyle(0,16777215,20);
   var _loc4_ = this.sList;
   var _loc3_;
   for(var _loc6_ in _loc4_)
   {
      _loc3_ = _loc4_[_loc6_];
      static_rend.DrawLine(_loc3_.p0,_loc3_.p1);
   }
   var _loc5_ = this.pList;
   var _loc2_;
   for(_loc6_ in _loc5_)
   {
      _loc2_ = _loc5_[_loc6_];
      static_rend.DrawAABB(_loc2_.pos,_loc2_.xw,_loc2_.yw);
   }
};
Ragdoll.prototype.Draw = function()
{
   var _loc10_ = this.sList;
   var _loc11_ = 0.017453292519943295;
   var _loc6_;
   var _loc5_;
   var _loc7_;
   var _loc9_;
   var _loc3_;
   var _loc2_;
   var _loc8_;
   var _loc4_;
   for(var _loc12_ in _loc10_)
   {
      _loc6_ = _loc10_[_loc12_];
      _loc5_ = _loc6_.mc;
      _loc7_ = _loc6_.p0;
      _loc9_ = _loc6_.p1;
      _loc3_ = _loc9_.x - _loc7_.x;
      _loc2_ = _loc9_.y - _loc7_.y;
      _loc5_._x = _loc7_.x;
      _loc5_._y = _loc7_.y;
      _loc8_ = Math.sqrt(_loc3_ * _loc3_ + _loc2_ * _loc2_);
      _loc5_.gotoAndStop(1 + Math.floor(100 * (_loc8_ / _loc6_.maxlen)));
      _loc3_ /= _loc8_;
      _loc2_ /= _loc8_;
      _loc4_ = 0;
      if(_loc3_ == 0)
      {
         if(_loc2_ < 0)
         {
            _loc4_ = -90;
         }
         else if(0 < _loc2_)
         {
            _loc4_ = 90;
         }
      }
      else if(_loc2_ == 0)
      {
         if(_loc3_ < 0)
         {
            _loc4_ = 180;
         }
         else
         {
            _loc4_ = 0;
         }
      }
      else
      {
         _loc4_ = Math.atan(_loc2_ / _loc3_) / _loc11_;
         if(_loc3_ < 0)
         {
            _loc4_ += 180;
         }
      }
      _loc5_._rotation = _loc4_;
   }
};
