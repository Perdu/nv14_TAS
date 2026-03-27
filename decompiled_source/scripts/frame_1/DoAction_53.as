function CollideRayvsTiles(out, p0, p1)
{
   var _loc1_ = tiles.GetTile_V(p0);
   var _loc20_ = _loc1_.i;
   var _loc19_ = _loc1_.j;
   var _loc8_ = p1.x - p0.x;
   var _loc7_ = p1.y - p0.y;
   var _loc18_ = Math.sqrt(_loc8_ * _loc8_ + _loc7_ * _loc7_);
   var _loc17_;
   var _loc16_;
   var _loc13_;
   var _loc11_;
   var _loc15_;
   var _loc12_;
   var _loc10_;
   var _loc14_;
   var _loc5_;
   var _loc4_;
   var _loc2_;
   var _loc3_;
   if(_loc18_ != 0)
   {
      _loc8_ /= _loc18_;
      _loc7_ /= _loc18_;
      _loc17_ = _loc20_;
      _loc16_ = _loc19_;
      if(_loc8_ < 0)
      {
         _loc13_ = -1;
         _loc11_ = (_loc1_.pos.x - _loc1_.xw - p0.x) / _loc8_;
         _loc15_ = 2 * _loc1_.xw / (- _loc8_);
      }
      else if(0 < _loc8_)
      {
         _loc13_ = 1;
         _loc11_ = (_loc1_.pos.x + _loc1_.xw - p0.x) / _loc8_;
         _loc15_ = 2 * _loc1_.xw / _loc8_;
      }
      else
      {
         _loc13_ = 0;
         _loc11_ = 100000000;
         _loc15_ = 0;
      }
      if(_loc7_ < 0)
      {
         _loc12_ = -1;
         _loc10_ = (_loc1_.pos.y - _loc1_.yw - p0.y) / _loc7_;
         _loc14_ = 2 * _loc1_.yw / (- _loc7_);
      }
      else if(0 < _loc7_)
      {
         _loc12_ = 1;
         _loc10_ = (_loc1_.pos.y + _loc1_.yw - p0.y) / _loc7_;
         _loc14_ = 2 * _loc1_.yw / _loc7_;
      }
      else
      {
         _loc12_ = 0;
         _loc10_ = 100000000;
         _loc14_ = 0;
      }
      _loc5_ = p0.x;
      _loc4_ = p0.y;
      if(TestRayTile(out,_loc5_,_loc4_,_loc8_,_loc7_,_loc1_))
      {
         return true;
      }
      while(_loc1_ != null)
      {
         if(_loc11_ < _loc10_)
         {
            if(_loc13_ < 0)
            {
               _loc2_ = _loc1_.eL;
               _loc3_ = _loc1_.nL;
            }
            else
            {
               _loc2_ = _loc1_.eR;
               _loc3_ = _loc1_.nR;
            }
            if(0 < _loc2_)
            {
               _loc5_ = p0.x + _loc11_ * _loc8_;
               _loc4_ = p0.y + _loc11_ * _loc7_;
               if(_loc2_ == EID_SOLID)
               {
                  out.x = _loc5_;
                  out.y = _loc4_;
                  return true;
               }
               if(TestRayTile(out,_loc5_,_loc4_,_loc8_,_loc7_,_loc3_))
               {
                  return true;
               }
            }
            _loc11_ += _loc15_;
            _loc17_ += _loc13_;
         }
         else
         {
            if(_loc12_ < 0)
            {
               _loc2_ = _loc1_.eU;
               _loc3_ = _loc1_.nU;
            }
            else
            {
               _loc2_ = _loc1_.eD;
               _loc3_ = _loc1_.nD;
            }
            if(0 < _loc2_)
            {
               _loc5_ = p0.x + _loc10_ * _loc8_;
               _loc4_ = p0.y + _loc10_ * _loc7_;
               if(_loc2_ == EID_SOLID)
               {
                  out.x = _loc5_;
                  out.y = _loc4_;
                  return true;
               }
               if(TestRayTile(out,_loc5_,_loc4_,_loc8_,_loc7_,_loc3_))
               {
                  return true;
               }
            }
            _loc10_ += _loc14_;
            _loc16_ += _loc12_;
         }
         _loc1_ = _loc3_;
      }
      return false;
   }
   return false;
}
