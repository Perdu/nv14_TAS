PlayerObject.prototype.Draw_Normal = function()
{
   this.prevframe = this.mc._currentframe;
   this.Render();
};
PlayerObject.prototype.Draw_Ragdoll = function()
{
   this.raggy.Draw();
};
PlayerObject.prototype.FaceMovement = function()
{
   var _loc2_ = this.pos.x - this.oldpos.x;
   if(_loc2_ != 0)
   {
      if(0 < _loc2_)
      {
         this.FaceDirection(1);
      }
      else if(_loc2_ < 0)
      {
         this.FaceDirection(-1);
      }
   }
};
PlayerObject.prototype.RenderWallSlide = function()
{
   this.mc._x = this.pos.x;
   this.mc._y = this.pos.y;
};
PlayerObject.prototype.RenderInAir = function()
{
   this.FaceMovement();
   this.mc._x = this.pos.x;
   this.mc._y = this.pos.y;
   var _loc2_ = this.pos.y - this.oldpos.y;
   var _loc5_ = -1;
   var _loc4_ = 2.5;
   var _loc3_ = 0;
   if(_loc2_ < 0)
   {
      if(_loc2_ < _loc5_)
      {
         _loc3_ = -1;
      }
      else
      {
         _loc3_ = - _loc2_ / _loc5_;
      }
   }
   else if(_loc4_ < _loc2_)
   {
      _loc3_ = 1;
   }
   else
   {
      _loc3_ = Math.sqrt(_loc2_ / _loc4_);
   }
   var _loc6_ = Math.floor(_loc3_ * 9);
   this.mc.gotoAndStop(94 + _loc6_);
};
PlayerObject.prototype.RenderRun = function()
{
   this.FaceMovement();
   this.mc.gotoAndStop(this.runanimcurframe);
   this.mc._x = this.pos.x;
   this.mc._y = this.pos.y;
   var _loc3_ = this.floorN.x;
   var _loc4_ = this.floorN.y;
   var _loc2_ = 0;
   if(_loc3_ == 0)
   {
      _loc2_ = -90;
   }
   else if(_loc4_ == 0)
   {
      if(_loc3_ < 0)
      {
         _loc2_ = 180;
      }
      else
      {
         _loc2_ = 0;
      }
   }
   else
   {
      _loc2_ = Math.atan(_loc4_ / _loc3_) / 0.017453292519943295;
      if(_loc3_ < 0)
      {
         _loc2_ += 180;
      }
   }
   _loc2_ += 90;
   this.mc._rotation = _loc2_;
};
PlayerObject.prototype.AdvanceRunAnim = function(vx, vy, nx, ny)
{
   var _loc5_ = Math.abs(vx * (- ny) + vy * nx);
   var _loc3_ = 13;
   var _loc8_ = 0.9;
   var _loc6_ = 72;
   var _loc9_ = this.mc._currentframe - _loc3_;
   var _loc2_ = _loc5_ / _loc8_;
   _loc2_ += this.runanimleftovers;
   var _loc4_ = Math.floor(_loc2_);
   this.runanimleftovers = _loc2_ - _loc4_;
   var _loc7_ = (_loc9_ + _loc4_) % _loc6_;
   this.runanimcurframe = _loc3_ + _loc7_;
};
PlayerObject.prototype.RenderDebug = function()
{
   static_rend.SetStyle(0,0,25);
   static_rend.DrawAABB(this.pos,this.xw,this.yw);
   static_rend.DrawCircle(this.pos,this.r);
};
PlayerObject.prototype.RenderStatic = function()
{
   this.FaceMovement();
   this.mc._x = this.pos.x;
   this.mc._y = this.pos.y;
};
PlayerObject.prototype.RenderStatic_Ground = function()
{
   this.FaceMovement();
   this.mc._x = this.pos.x;
   this.mc._y = this.pos.y;
   var _loc3_ = this.floorN.x;
   var _loc4_ = this.floorN.y;
   var _loc2_ = 0;
   if(_loc3_ == 0)
   {
      _loc2_ = -90;
   }
   else if(_loc4_ == 0)
   {
      if(_loc3_ < 0)
      {
         _loc2_ = 180;
      }
      else
      {
         _loc2_ = 0;
      }
   }
   else
   {
      _loc2_ = Math.atan(_loc4_ / _loc3_) / 0.017453292519943295;
      if(_loc3_ < 0)
      {
         _loc2_ += 180;
      }
   }
   _loc2_ += 90;
   this.mc._rotation = _loc2_;
};
