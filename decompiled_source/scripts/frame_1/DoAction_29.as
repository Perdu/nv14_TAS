function CollideAABBvsTileMap(box)
{
   var _loc4_ = box.pos;
   var _loc1_ = tiles.GetTile_V(_loc4_);
   box.cell = _loc1_;
   var _loc18_ = _loc1_.pos.x;
   var _loc11_ = _loc1_.pos.y;
   var _loc15_ = _loc1_.xw;
   var _loc14_ = _loc1_.yw;
   var _loc9_ = _loc4_.x - _loc18_;
   var _loc8_ = _loc4_.y - _loc11_;
   var _loc22_;
   var _loc20_;
   if(0 < _loc1_.ID)
   {
      _loc22_ = _loc15_ + box.xw - Math.abs(_loc9_);
      _loc20_ = _loc14_ + box.yw - Math.abs(_loc8_);
      if(_loc22_ < _loc20_)
      {
         if(_loc9_ < 0)
         {
            _loc22_ *= -1;
            _loc20_ = 0;
         }
         else
         {
            _loc20_ = 0;
         }
      }
      else if(_loc8_ < 0)
      {
         _loc22_ = 0;
         _loc20_ *= -1;
      }
      else
      {
         _loc22_ = 0;
      }
      ResolveBoxTile(_loc22_,_loc20_,box,_loc1_);
   }
   var _loc28_ = false;
   var _loc21_ = false;
   _loc8_ = _loc4_.y - _loc11_;
   _loc20_ = Math.abs(_loc8_) + box.yw - _loc14_;
   var _loc7_;
   var _loc26_;
   var _loc13_;
   var _loc16_;
   if(0 < _loc20_)
   {
      _loc28_ = true;
      if(_loc8_ < 0)
      {
         _loc7_ = _loc1_.eU;
         _loc26_ = _loc1_.nU;
         _loc13_ = _loc20_;
         _loc16_ = 1;
      }
      else
      {
         _loc7_ = _loc1_.eD;
         _loc26_ = _loc1_.nD;
         _loc13_ = - _loc20_;
         _loc16_ = -1;
      }
      if(0 < _loc7_)
      {
         if(_loc7_ == EID_SOLID)
         {
            _loc21_ = COL_AXIS;
            box.ReportCollisionVsWorld(0,_loc13_,0,_loc16_,_loc26_);
         }
         else
         {
            _loc21_ = ResolveBoxTile(0,_loc13_,box,_loc26_);
         }
      }
   }
   var _loc27_ = false;
   var _loc19_ = false;
   _loc9_ = _loc4_.x - _loc18_;
   _loc22_ = Math.abs(_loc9_) + box.xw - _loc15_;
   var _loc10_;
   var _loc23_;
   var _loc12_;
   var _loc17_;
   if(0 < _loc22_)
   {
      _loc27_ = true;
      if(_loc9_ < 0)
      {
         _loc10_ = _loc1_.eL;
         _loc23_ = _loc1_.nL;
         _loc12_ = _loc22_;
         _loc17_ = 1;
      }
      else
      {
         _loc10_ = _loc1_.eR;
         _loc23_ = _loc1_.nR;
         _loc12_ = - _loc22_;
         _loc17_ = -1;
      }
      if(0 < _loc10_)
      {
         if(_loc10_ == EID_SOLID)
         {
            _loc19_ = COL_AXIS;
            box.ReportCollisionVsWorld(_loc12_,0,_loc17_,0,_loc23_);
         }
         else
         {
            _loc19_ = ResolveBoxTile(_loc12_,0,box,_loc23_);
         }
      }
   }
   var _loc6_;
   var _loc5_;
   var _loc30_;
   var _loc3_;
   var _loc25_;
   var _loc24_;
   var _loc29_;
   if(_loc27_ && _loc19_ != COL_AXIS && _loc28_ && _loc21_ != COL_AXIS)
   {
      _loc9_ = _loc4_.x - _loc18_;
      _loc8_ = _loc4_.y - _loc11_;
      _loc22_ = Math.abs(_loc9_) + box.xw - _loc15_;
      _loc20_ = Math.abs(_loc8_) + box.yw - _loc14_;
      _loc6_ = 0;
      _loc5_ = 0;
      _loc30_ = false;
      if(_loc9_ < 0 && _loc8_ < 0)
      {
         _loc10_ = _loc1_.nU.eL;
         _loc7_ = _loc1_.nL.eU;
         _loc3_ = _loc1_.nU.nL;
      }
      else if(_loc9_ < 0 && 0 < _loc8_)
      {
         _loc10_ = _loc1_.nD.eL;
         _loc7_ = _loc1_.nL.eD;
         _loc3_ = _loc1_.nD.nL;
      }
      else if(0 < _loc9_ && 0 < _loc8_)
      {
         _loc10_ = _loc1_.nD.eR;
         _loc7_ = _loc1_.nR.eD;
         _loc3_ = _loc1_.nD.nR;
      }
      else if(0 < _loc9_ && _loc8_ < 0)
      {
         _loc10_ = _loc1_.nU.eR;
         _loc7_ = _loc1_.nR.eU;
         _loc3_ = _loc1_.nU.nR;
      }
      if(_loc22_ < _loc20_)
      {
         _loc5_ = _loc24_ = 0;
         if(_loc9_ < 0)
         {
            _loc6_ = _loc22_;
            _loc25_ = 1;
         }
         else
         {
            _loc6_ = - _loc22_;
            _loc25_ = -1;
         }
      }
      else
      {
         _loc6_ = _loc25_ = 0;
         if(_loc8_ < 0)
         {
            _loc5_ = _loc20_;
            _loc24_ = 1;
         }
         else
         {
            _loc5_ = - _loc20_;
            _loc24_ = -1;
         }
      }
      if(0 < _loc10_)
      {
         if(0 < _loc7_)
         {
            if(_loc10_ == EID_SOLID)
            {
               if(_loc7_ == EID_SOLID)
               {
                  box.ReportCollisionVsWorld(_loc6_,_loc5_,_loc25_,_loc24_,_loc3_);
               }
               else
               {
                  _loc29_ = ResolveBoxTile(_loc6_,_loc5_,box,_loc3_);
                  if(_loc29_ == COL_NONE)
                  {
                     box.ReportCollisionVsWorld(_loc12_,0,_loc17_,0,_loc3_);
                  }
               }
            }
            else if(_loc7_ == EID_SOLID)
            {
               _loc29_ = ResolveBoxTile(_loc6_,_loc5_,box,_loc3_);
               if(_loc29_ == COL_NONE)
               {
                  box.ReportCollisionVsWorld(0,_loc13_,0,_loc16_,_loc3_);
               }
            }
            else
            {
               ResolveBoxTile(_loc6_,_loc5_,box,_loc3_);
            }
         }
         else if(_loc10_ == EID_SOLID)
         {
            box.ReportCollisionVsWorld(_loc12_,0,_loc17_,0,_loc3_);
         }
         else
         {
            ResolveBoxTile(_loc6_,_loc5_,box,_loc3_);
         }
      }
      else if(0 < _loc7_)
      {
         if(_loc7_ == EID_SOLID)
         {
            box.ReportCollisionVsWorld(0,_loc13_,0,_loc16_,_loc3_);
         }
         else
         {
            ResolveBoxTile(_loc6_,_loc5_,box,_loc3_);
         }
      }
   }
}
