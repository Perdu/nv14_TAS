function RotateAIDir(curDir, rot)
{
   if(rot < 0 || AI_ROT_270 < rot)
   {
      return curDir;
   }
   return (curDir + rot) % 4;
}
DRONEMOVE_SURFACEFOLLOW_CW = 0;
DRONEMOVE_SURFACEFOLLOW_CCW = 1;
DRONEMOVE_WANDER_CW = 2;
DRONEMOVE_WANDER_CCW = 3;
DRONEMOVE_WANDER_ALTERNATING = 4;
DRONEMOVE_WANDER_RANDOM = 5;
AI_DIR_R = 0;
AI_DIR_D = 1;
AI_DIR_L = 2;
AI_DIR_U = 3;
AI_ROT_0 = 0;
AI_ROT_90 = 1;
AI_ROT_180 = 2;
AI_ROT_270 = 3;
MoveList_ChuChuCW = new Array();
MoveList_ChuChuCW.push(AI_ROT_0);
MoveList_ChuChuCW.push(AI_ROT_90);
MoveList_ChuChuCW.push(AI_ROT_270);
MoveList_ChuChuCW.push(AI_ROT_180);
MoveList_ChuChuCCW = new Array();
MoveList_ChuChuCCW.push(AI_ROT_0);
MoveList_ChuChuCCW.push(AI_ROT_270);
MoveList_ChuChuCCW.push(AI_ROT_90);
MoveList_ChuChuCCW.push(AI_ROT_180);
MoveList_SurfaceCW = new Array();
MoveList_SurfaceCW.push(AI_ROT_90);
MoveList_SurfaceCW.push(AI_ROT_0);
MoveList_SurfaceCW.push(AI_ROT_270);
MoveList_SurfaceCW.push(AI_ROT_180);
MoveList_SurfaceCCW = new Array();
MoveList_SurfaceCCW.push(AI_ROT_270);
MoveList_SurfaceCCW.push(AI_ROT_0);
MoveList_SurfaceCCW.push(AI_ROT_90);
MoveList_SurfaceCCW.push(AI_ROT_180);
DroneObject.prototype.SetDir = function(dir)
{
   if(this.dir != this.curDir)
   {
      this.curDir = dir;
      this.curDirV = this.dirList[this.curDir];
      if(dir < 2)
      {
         if(dir == 0)
         {
            this.curRot = 0;
         }
         else
         {
            this.curRot = 90;
         }
      }
      else if(dir == 2)
      {
         this.curRot = 180;
      }
      else
      {
         this.curRot = -90;
      }
   }
};
DroneObject.prototype.TestEdge = function(dir)
{
   var _loc2_;
   var _loc3_;
   if(dir == AI_DIR_U)
   {
      _loc2_ = this.cell.eU;
      _loc3_ = this.cell.nU;
   }
   else if(dir == AI_DIR_L)
   {
      _loc2_ = this.cell.eL;
      _loc3_ = this.cell.nL;
   }
   else if(dir == AI_DIR_D)
   {
      _loc2_ = this.cell.eD;
      _loc3_ = this.cell.nD;
   }
   else
   {
      if(dir != AI_DIR_R)
      {
         return false;
      }
      _loc2_ = this.cell.eR;
      _loc3_ = this.cell.nR;
   }
   if(_loc2_ == EID_OFF)
   {
      this.goal.x = _loc3_.pos.x;
      this.goal.y = _loc3_.pos.y;
      return true;
   }
   return false;
};
DroneObject.prototype.Chase_NoSearch = function()
{
   return false;
};
DroneObject.prototype.Chase_SurfaceGrab = function()
{
   this.Chase = this.Chase_AxisSearch;
   this.SetDir(this.surfaceFutureDir);
   return false;
};
DroneObject.prototype.Chase_AxisSearch = function()
{
   var _loc5_ = player.cell.i - this.cell.i;
   var _loc3_ = player.cell.j - this.cell.j;
   var _loc2_;
   var _loc4_;
   if(Math.abs(_loc5_) < 1)
   {
      _loc4_ = Math.abs(_loc3_);
      if(player.pos.y < this.pos.y)
      {
         if(this.curDir == AI_DIR_D)
         {
            return false;
         }
         _loc2_ = AI_DIR_U;
      }
      else
      {
         if(this.curDir == AI_DIR_U)
         {
            return false;
         }
         _loc2_ = AI_DIR_D;
      }
   }
   else
   {
      if(Math.abs(_loc3_) >= 1)
      {
         return false;
      }
      _loc4_ = Math.abs(_loc5_);
      if(player.pos.x < this.pos.x)
      {
         if(this.curDir == AI_DIR_R)
         {
            return false;
         }
         _loc2_ = AI_DIR_L;
      }
      else
      {
         if(this.curDir == AI_DIR_L)
         {
            return false;
         }
         _loc2_ = AI_DIR_R;
      }
   }
   if(this.FindTarget(_loc2_,_loc4_))
   {
      this.SetDir(_loc2_);
      if(this.DRONEMOVE < DRONEMOVE_WANDER_CW)
      {
         this.Chase = this.Chase_SurfaceGrab;
         if(this.DRONEMOVE == DRONEMOVE_SURFACEFOLLOW_CW)
         {
            rot = AI_ROT_270;
         }
         else
         {
            if(this.DRONEMOVE != DRONEMOVE_SURFACEFOLLOW_CCW)
            {
               return false;
            }
            rot = AI_ROT_90;
         }
         this.surfaceFutureDir = RotateAIDir(_loc2_,rot);
      }
      return true;
   }
   return false;
};
DroneObject.prototype.FindTarget = function(dir, t)
{
   var _loc3_ = 0;
   var _loc2_ = this.cell;
   if(dir < 2)
   {
      if(dir == AI_DIR_R)
      {
         while(_loc3_ < t)
         {
            _loc3_ = _loc3_ + 1;
            if(_loc2_.eR != EID_OFF)
            {
               return false;
            }
            _loc2_ = _loc2_.nR;
         }
         while(_loc2_.eR == EID_OFF)
         {
            _loc3_ = _loc3_ + 1;
            _loc2_ = _loc2_.nR;
         }
         this.goal.x = this.cell.pos.x + _loc3_ * (2 * this.cell.xw);
         return true;
      }
      if(dir == AI_DIR_D)
      {
         while(_loc3_ < t)
         {
            _loc3_ = _loc3_ + 1;
            if(_loc2_.eD != EID_OFF)
            {
               return false;
            }
            _loc2_ = _loc2_.nD;
         }
         while(_loc2_.eD == EID_OFF)
         {
            _loc3_ = _loc3_ + 1;
            _loc2_ = _loc2_.nD;
         }
         this.goal.y = this.cell.pos.y + _loc3_ * (2 * this.cell.yw);
         return true;
      }
      return false;
   }
   if(dir == AI_DIR_L)
   {
      while(_loc3_ < t)
      {
         _loc3_ = _loc3_ + 1;
         if(_loc2_.eL != EID_OFF)
         {
            return false;
         }
         _loc2_ = _loc2_.nL;
      }
      while(_loc2_.eL == EID_OFF)
      {
         _loc3_ = _loc3_ + 1;
         _loc2_ = _loc2_.nL;
      }
      this.goal.x = this.cell.pos.x - _loc3_ * (2 * this.cell.xw);
      return true;
   }
   if(dir == AI_DIR_U)
   {
      while(_loc3_ < t)
      {
         _loc3_ = _loc3_ + 1;
         if(_loc2_.eU != EID_OFF)
         {
            return false;
         }
         _loc2_ = _loc2_.nU;
      }
      while(_loc2_.eU == EID_OFF)
      {
         _loc3_ = _loc3_ + 1;
         _loc2_ = _loc2_.nU;
      }
      this.goal.y = this.cell.pos.y - _loc3_ * (2 * this.cell.yw);
      return true;
   }
   return false;
};
DroneObject.prototype.GetNewGoal_Simple = function()
{
   var _loc3_ = this.moveList;
   var _loc4_ = this.curDir;
   var _loc2_ = RotateAIDir(_loc4_,_loc3_[0]);
   if(this.TestEdge(_loc2_))
   {
      return _loc2_;
   }
   _loc2_ = RotateAIDir(_loc4_,_loc3_[1]);
   if(this.TestEdge(_loc2_))
   {
      return _loc2_;
   }
   _loc2_ = RotateAIDir(_loc4_,_loc3_[2]);
   if(this.TestEdge(_loc2_))
   {
      return _loc2_;
   }
   _loc2_ = RotateAIDir(_loc4_,_loc3_[3]);
   if(this.TestEdge(_loc2_))
   {
      return _loc2_;
   }
};
DroneObject.prototype.GetNewGoal_ChuChuAlternating = function()
{
   var _loc2_;
   if(this.ai_counter2 == 0)
   {
      this.moveList = MoveList_ChuChuCW;
      _loc2_ = this.GetNewGoal_Simple();
      if(_loc2_ != this.curDir)
      {
         this.ai_counter2 = 1;
      }
      return _loc2_;
   }
   this.moveList = MoveList_ChuChuCCW;
   _loc2_ = this.GetNewGoal_Simple();
   if(_loc2_ != this.curDir)
   {
      this.ai_counter2 = 0;
   }
   return _loc2_;
};
DroneObject.prototype.GetNewGoal_ChuChuRandom = function()
{
   var _loc2_;
   if(this.ai_counter % 2 == 0)
   {
      this.moveList = MoveList_ChuChuCW;
      _loc2_ = this.GetNewGoal_Simple();
      if(_loc2_ != this.curDir)
      {
         this.ai_counter = 1;
      }
      return _loc2_;
   }
   this.moveList = MoveList_ChuChuCCW;
   _loc2_ = this.GetNewGoal_Simple();
   if(_loc2_ != this.curDir)
   {
      this.ai_counter = 0;
   }
   return _loc2_;
};
