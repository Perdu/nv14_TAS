if(_root.ninjastateText == undefined)
{
   _root.createTextField("ninjastateText",999998,675,3,75,20);
   _root.ninjastateText.textColor = 0;
   _root.ninjastateText.background = true;
   _root.ninjastateText.backgroundColor = 16777215;
}
PSTATE_STANDING = 0;
PSTATE_RUNNING = 1;
PSTATE_SKIDDING = 2;
PSTATE_JUMPING = 3;
PSTATE_FALLING = 4;
PSTATE_WALLSLIDING = 5;
PSTATE_RAGDOLL = 6;
PSTATE_CELEBRATING = 7;
PlayerObject.prototype.Think = function()
{
   game.GetInputState(this.inputList);
   var _loc4_ = this.inputList;
   var _loc5_ = _loc4_[PINPUT_R];
   var _loc6_ = _loc4_[PINPUT_L];
   var _loc7_ = _loc4_[PINPUT_J];
   var _loc8_ = _loc4_[PINPUT_JTRIG];
   var _loc9_ = this.pos.x - this.oldpos.x;
   var _loc10_ = this.pos.y - this.oldpos.y;
   var _loc11_ = this.curState;
   _global.tas_curState = this.curState;
   var _loc12_ = "";
   if(this.curState == 0)
   {
      _loc12_ = "Standing";
   }
   else if(this.curState == 1)
   {
      _loc12_ = "Running";
   }
   else if(this.curState == 2)
   {
      _loc12_ = "Skidding";
   }
   else if(this.curState == 3)
   {
      _loc12_ = "Jumping";
   }
   else if(this.curState == 4)
   {
      _loc12_ = "Falling";
   }
   else if(this.curState == 5)
   {
      _loc12_ = "Wallsliding";
   }
   else if(this.curState == 6)
   {
      _loc12_ = "Ragdoll";
   }
   else if(this.curState == 7)
   {
      _loc12_ = "Celebrating";
   }
   _root.ninjastateText.text = _loc12_;
   var _loc13_ = 1;
   var _loc14_ = 0;
   if(_loc6_)
   {
      _loc14_ -= 1;
   }
   if(_loc5_)
   {
      _loc14_ += 1;
   }
   var _loc15_;
   var _loc16_;
   var _loc17_;
   var _loc18_;
   var _loc19_;
   var _loc20_;
   var _loc21_;
   var _loc22_;
   var _loc23_;
   var _loc24_;
   var _loc25_;
   var _loc26_;
   var _loc27_;
   var _loc28_;
   var _loc29_;
   var _loc30_;
   var _loc31_;
   if(this.IN_AIR)
   {
      _loc15_ = this.mc._rotation;
      this.mc._rotation -= 0.1 * _loc15_;
      _loc16_ = _loc9_ + _loc14_ * this.airAccel;
      if(Math.abs(_loc16_) < this.maxspeedAir)
      {
         _loc9_ = _loc16_;
      }
      this.oldpos.x = this.pos.x - _loc9_;
      if(_loc11_ < 3)
      {
         this.Fall();
         return undefined;
      }
      if(_loc11_ == PSTATE_JUMPING)
      {
         this.jumptimer += 1;
         if(!_loc7_ || this.jumptimer > this.max_jump_time)
         {
            this.Fall();
            return undefined;
         }
         return undefined;
      }
      if(_loc11_ == PSTATE_FALLING)
      {
      }
      if(this.NEAR_WALL)
      {
         if(_loc8_)
         {
            _loc17_ = 0;
            _loc18_ = 0;
            if(_loc11_ == PSTATE_WALLSLIDING && _loc14_ * this.wallN.x < 0)
            {
               _loc17_ = 1;
               _loc18_ = 0.5;
            }
            else
            {
               _loc17_ = 1.5;
               _loc18_ = 0.7;
            }
            particles.SpawnJumpDust(this.pos.x - this.wallN.x * this.r,this.pos.y - this.wallN.y * this.r,this.wallN.x * 90);
            this.Jump(this.wallN.x * _loc17_,this.wallN.y - _loc18_);
            if (this.NEAR_OBJECT && this.NEAR_OBJECT_type == OBJTYPE_BOUNCEBLOCK) {
                if (game.tickCounter - this.last_bbwj < 10) {
                    if (game.tickCounter - this.last_doublebbwj < 10) {
                        if (game.tickCounter - this.last_triplebbwj < 10) {
                            this.techwrite("Quad bbwj", 0xFFFF0000);
                        } else {
                            this.techwrite("Triple bbwj", 0xFFAA0000);
                        }
                        this.last_triplebbwj = game.tickCounter;
                    } else {
                        this.techwrite("Double bbwj", 0xFF330000);
                    }
                    this.last_doublebbwj = game.tickCounter;
                } else {
                    if (this.object_bbwj_position) {
                        this.techwrite("bbbbwj", 0xFF880000);
                    } else {
                        this.techwrite("bbwj", 0xFF555555);
                    }
                }
                this.last_bbwj = game.tickCounter;
            } else if (this.NEAR_OBJECT && this.NEAR_OBJECT_type == OBJTYPE_THWOMP) {
                if (this.object_bbwj_position) {
                    this.techwrite("Thwump bwj", 0xFF880000);
                } else {
                    this.techwrite("Thwump wj", 0xFF555555);
                }
            } else {
                this.techwrite("wj", 0xFF555555);
            }
            return undefined;
         }
         if(_loc11_ == PSTATE_WALLSLIDING)
         {
            if(0 < _loc14_ * this.wallN.x)
            {
               this.Fall();
               return undefined;
            }
            _loc19_ = Math.abs(_loc10_);
            _loc20_ = (- this.wallFriction) * _loc13_ * _loc19_;
            this.oldpos.y = this.pos.y - (_loc10_ + _loc20_);
            particles.SpawnWallDust(this.pos,this.r,this.wallN,_loc19_);
            _loc21_ = Math.min(100,Math.floor(_loc19_ * 70));
            this.sndControl.setVolume(_loc21_);
            return undefined;
         }
         if(0 < _loc10_ && _loc14_ * this.wallN.x < 0)
         {
            this.Wallslide();
            this.techwrite("wallslide", 0xFF555555)
            return undefined;
         }
      }
      else if(_loc11_ == PSTATE_WALLSLIDING)
      {
         this.Fall();
         return undefined;
      }
   }
   else
   {
      _loc16_ = _loc9_ + _loc13_ * _loc14_ * this.groundAccel;
      if(Math.abs(_loc16_) < this.maxspeedGround)
      {
         _loc9_ = _loc16_;
      }
      this.oldpos.x = this.pos.x - _loc9_;
      if(2 < _loc11_)
      {
         particles.SpawnLandDust(this.pos.x - this.r * this.floorN.x,this.pos.y - this.r * this.floorN.y,NormToRot(this.floorN.x,this.floorN.y) + 90,Math.abs(_loc9_) + _loc10_);
         this.snd.gotoAndPlay("land");
         if(0 < _loc9_ * _loc14_)
         {
            this.Run(_loc14_);
            return undefined;
         }
         this.Skid();
         return undefined;
      }
      if(_loc8_)
      {
         particles.SpawnJumpDust(this.pos.x - this.floorN.x * this.r,this.pos.y - this.floorN.y * this.r,this.mc._rotation);
         if(_loc14_ * this.floorN.x < 0)
         {
            this.Jump(0,-0.7);
            if (game.tickCounter - this.last_jump < 10) {
                this.techwrite("Double Jump", 0xFF550000);
            } else if (game.tickCounter - this.last_slope_jump < 10) {
                this.techwrite("Double Jump", 0xFF550000);
            } else {
                this.techwrite("Slope Jump", 0xFF555555);
            }
            this.last_slope_jump = game.tickCounter;
            this.last_jump = 0;
         }
         else
         {
             trace("Jump: " + this.floorN.x + ", " + this.floorN.y);
             trace("poses: " + this.pos.x + ", " + this.pos.y + "; " + this.oldpos.x + ", " + this.oldpos.y);
            if (this.floorN.x == 0 && this.floorN.y == -1) {
                this.techwrite("Jump", 0XFF555555);
            } else if ((this.pos.x < this.oldpos.x && this.floorN.x < 0) || (this.pos.x > this.oldpos.x && this.floorN.x >= 0)) {
                this.techwrite("cj", 0XFF000000);
            } else {
                this.techwrite("rcj", 0XFF000000);
            }
            this.Jump(this.floorN.x,this.floorN.y);
            this.last_jump = game.tickCounter;
            this.last_slope_jump = 0;
         }
         return undefined;
      }
      if(_loc11_ != PSTATE_RUNNING)
      {
         if(_loc11_ == PSTATE_SKIDDING)
         {
            _loc22_ = this.floorN.x;
            _loc23_ = this.floorN.y;
            _loc24_ = Math.abs(_loc9_ * (- _loc23_) + _loc10_ * _loc22_);
            _loc25_ = _loc9_ * _loc24_;
            if(0 < _loc25_ * _loc14_)
            {
               this.Run(_loc14_);
               return undefined;
            }
            particles.SpawnFloorDust(this.pos,this.r,this.floorN,this.mc._rotation,this.facingDir,_loc24_);
            if(_loc24_ < 0.1)
            {
               this.Stand();
               return undefined;
            }
            _loc26_ = this.skidFriction * _loc13_;
            _loc9_ *= _loc26_;
            this.oldpos.x = this.pos.x - _loc9_;
            _loc21_ = Math.min(100,Math.floor(_loc24_ * 100));
            this.sndControl.setVolume(_loc21_);
            return undefined;
         }
         if(_loc14_ != 0)
         {
            this.Run(_loc14_);
            return undefined;
         }
         _loc22_ = this.floorN.x;
         _loc23_ = this.floorN.y;
         _loc24_ = Math.abs(_loc9_ * (- _loc23_) + _loc10_ * _loc22_);
         if(0.1 <= _loc24_)
         {
            this.Skid();
            return undefined;
         }
         _loc26_ = this.standFriction * _loc13_;
         _loc9_ *= _loc26_;
         _loc10_ *= _loc26_;
         this.oldpos.x = this.pos.x - _loc9_;
         this.oldpos.y = this.pos.y - _loc10_;
         return undefined;
      }
      _loc22_ = this.floorN.x;
      _loc23_ = this.floorN.y;
      _loc24_ = _loc9_ * (- _loc23_) + _loc10_ * _loc22_;
      _loc27_ = Math.abs(_loc24_);
      _loc25_ = _loc9_ * _loc27_;
      if(_loc14_ * _loc25_ <= 0)
      {
         this.Skid();
         return undefined;
      }
      if(_loc14_ * _loc22_ < 0)
      {
         _loc20_ = - Math.abs(_loc22_);
         if(_loc22_ < 0)
         {
            _loc28_ = - _loc23_;
         }
         else
         {
            _loc28_ = _loc23_;
         }
         _loc29_ = Math.abs(_loc23_);
         _loc28_ *= 0.5 * _loc29_;
         _loc20_ *= 0.5 * _loc29_;
         _loc30_ = _loc9_ + _loc28_ * this.groundAccel;
         _loc31_ = _loc10_ + _loc20_ * this.groundAccel;
         if(Math.abs(_loc16_) < this.maxspeedGround)
         {
            _loc9_ = _loc30_;
            _loc10_ = _loc31_;
         }
         this.oldpos.x = this.pos.x - _loc9_;
         this.oldpos.y = this.pos.y - _loc10_;
      }
      this.AdvanceRunAnim(_loc9_,_loc10_,_loc22_,_loc23_);
   }
};
PlayerObject.prototype.ThinkRagdoll = function()
{
};
PlayerObject.prototype.ThinkCelebrate = function()
{
   var _loc2_;
   if(this.IN_AIR)
   {
      if(!this.celeb_wasinair)
      {
         this.d = this.normDrag;
         this.Render = this.RenderInAir;
         this.celeb_wasinair = true;
      }
   }
   else
   {
      if(this.celeb_wasinair)
      {
         this.d = this.winDrag;
         this.Render = this.RenderStatic_Ground;
         _loc2_ = Math.random();
         if(_loc2_ < 0.1111111111111111)
         {
            this.mc.gotoAndPlay("CELEBRATE_NEW8");
         }
         else if(_loc2_ < 0.2222222222222222)
         {
            this.mc.gotoAndPlay("CELEBRATE_NEW7");
         }
         else if(_loc2_ < 0.3333333333333333)
         {
            this.mc.gotoAndPlay("CELEBRATE_NEW6");
         }
         else if(_loc2_ < 0.4444444444444444)
         {
            this.mc.gotoAndPlay("CELEBRATE_NEW5");
         }
         else if(_loc2_ < 0.5555555555555556)
         {
            this.mc.gotoAndPlay("CELEBRATE_NEW4");
         }
         else if(_loc2_ < 0.6666666666666666)
         {
            this.mc.gotoAndPlay("CELEBRATE_NEW3");
         }
         else if(_loc2_ < 0.7777777777777778)
         {
            this.mc.gotoAndPlay("CELEBRATE_NEW2");
         }
         else if(_loc2_ < 0.8888888888888888)
         {
            this.mc.gotoAndPlay("CELEBRATE_NEW9");
         }
         else
         {
            this.mc.gotoAndPlay("CELEBRATE_NEW1");
         }
      }
      this.celeb_wasinair = false;
   }
};
