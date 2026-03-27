function CollideRayvsMap(out, p0, p1)
{
   var _loc2_ = tiles.GetTile_V(p0);
   var _loc40_ = _loc2_.i;
   var _loc39_ = _loc2_.j;
   var _loc6_ = p1.x - p0.x;
   var _loc5_ = p1.y - p0.y;
   var _loc38_ = Math.sqrt(_loc6_ * _loc6_ + _loc5_ * _loc5_);
   var _loc21_;
   var _loc20_;
   var _loc35_;
   var _loc17_;
   var _loc19_;
   var _loc34_;
   var _loc37_;
   var _loc36_;
   var _loc11_;
   var _loc10_;
   var _loc42_;
   var _loc41_;
   var _loc18_;
   var _loc4_;
   var _loc7_;
   var _loc9_;
   var _loc3_;
   var _loc25_;
   var _loc13_;
   var _loc16_;
   var _loc32_;
   var _loc31_;
   var _loc24_;
   var _loc12_;
   var _loc30_;
   var _loc22_;
   var _loc23_;
   var _loc27_;
   var _loc26_;
   var _loc15_;
   var _loc14_;
   var _loc29_;
   var _loc28_;
   var _loc8_;
   if(_loc38_ != 0)
   {
      _loc6_ /= _loc38_;
      _loc5_ /= _loc38_;
      if(_loc6_ < 0)
      {
         _loc21_ = -1;
         _loc20_ = (_loc2_.pos.x - _loc2_.xw - p0.x) / _loc6_;
         _loc35_ = 2 * _loc2_.xw / (- _loc6_);
      }
      else if(0 < _loc6_)
      {
         _loc21_ = 1;
         _loc20_ = (_loc2_.pos.x + _loc2_.xw - p0.x) / _loc6_;
         _loc35_ = 2 * _loc2_.xw / _loc6_;
      }
      else
      {
         _loc21_ = 0;
         _loc20_ = 100000000;
         _loc35_ = 0;
      }
      if(_loc5_ < 0)
      {
         _loc17_ = -1;
         _loc19_ = (_loc2_.pos.y - _loc2_.yw - p0.y) / _loc5_;
         _loc34_ = 2 * _loc2_.yw / (- _loc5_);
      }
      else if(0 < _loc5_)
      {
         _loc17_ = 1;
         _loc19_ = (_loc2_.pos.y + _loc2_.yw - p0.y) / _loc5_;
         _loc34_ = 2 * _loc2_.yw / _loc5_;
      }
      else
      {
         _loc17_ = 0;
         _loc19_ = 100000000;
         _loc34_ = 0;
      }
      _loc37_ = _loc40_;
      _loc36_ = _loc39_;
      _loc11_ = _loc42_ = p0.x;
      _loc10_ = _loc41_ = p0.y;
      if(TestRayTile(out,_loc42_,_loc41_,_loc6_,_loc5_,_loc2_))
      {
         return true;
      }
      static_rend.SetStyle(0,8947848,100);
      _loc18_ = new Vector2(0,0);
      _loc4_ = new Vector2(_loc11_,_loc10_);
      _loc24_ = false;
      _loc12_ = false;
      _loc30_ = false;
      _loc22_ = false;
      _loc23_ = false;
      while(true)
      {
         if(_loc2_ == null)
         {
            return false;
         }
         _loc18_.x = _loc4_.x;
         _loc18_.y = _loc4_.y;
         if(_loc20_ < _loc19_)
         {
            _loc4_.x = _loc11_ + _loc20_ * _loc6_;
            _loc4_.y = _loc10_ + _loc20_ * _loc5_;
            static_rend.DrawPlus(_loc4_);
            if(_loc21_ < 0)
            {
               _loc7_ = _loc2_.eL;
               _loc9_ = _loc2_.nL;
            }
            else
            {
               _loc7_ = _loc2_.eR;
               _loc9_ = _loc2_.nR;
            }
            if(!_loc12_ && 0 < _loc7_)
            {
               if(_loc7_ == EID_SOLID)
               {
                  out.x = _loc4_.x;
                  out.y = _loc4_.y;
                  _loc24_ = true;
                  _loc29_ = out.x;
                  _loc28_ = out.y;
               }
               else if(TestRayTile(out,_loc4_.x,_loc4_.y,_loc6_,_loc5_,_loc9_))
               {
                  _loc12_ = true;
                  _loc27_ = out.x;
                  _loc26_ = out.y;
               }
            }
            _loc20_ += _loc35_;
            _loc37_ += _loc21_;
         }
         else
         {
            _loc4_.x = _loc11_ + _loc19_ * _loc6_;
            _loc4_.y = _loc10_ + _loc19_ * _loc5_;
            static_rend.DrawPlus(_loc4_);
            if(_loc17_ < 0)
            {
               _loc7_ = _loc2_.eU;
               _loc9_ = _loc2_.nU;
            }
            else
            {
               _loc7_ = _loc2_.eD;
               _loc9_ = _loc2_.nD;
            }
            if(!_loc12_ && 0 < _loc7_)
            {
               if(_loc7_ == EID_SOLID)
               {
                  out.x = _loc4_.x;
                  out.y = _loc4_.y;
                  _loc24_ = true;
                  _loc29_ = out.x;
                  _loc28_ = out.y;
               }
               else if(TestRayTile(out,_loc4_.x,_loc4_.y,_loc6_,_loc5_,_loc9_))
               {
                  _loc12_ = true;
                  _loc27_ = out.x;
                  _loc26_ = out.y;
               }
            }
            _loc19_ += _loc34_;
            _loc36_ += _loc17_;
         }
         if(_loc21_ < 0)
         {
            if(_loc17_ < 0)
            {
               _loc16_ = _loc2_.nR.nU;
               _loc13_ = _loc2_.nL.nD;
            }
            else
            {
               _loc16_ = _loc2_.nL.nU;
               _loc13_ = _loc2_.nR.nD;
            }
         }
         else if(_loc17_ < 0)
         {
            _loc16_ = _loc2_.nR.nD;
            _loc13_ = _loc2_.nL.nU;
         }
         else
         {
            _loc16_ = _loc2_.nL.nD;
            _loc13_ = _loc2_.nR.nU;
         }
         _loc32_ = _loc18_.x - _loc2_.pos.x;
         _loc31_ = _loc18_.y - _loc2_.pos.y;
         if(_loc32_ * (- _loc5_) + _loc31_ * _loc6_ < 0)
         {
            _loc25_ = _loc13_;
         }
         else
         {
            _loc25_ = _loc16_;
         }
         _loc3_ = _loc2_.next;
         _loc8_ = null;
         while(_loc3_ != null)
         {
            if(TestRayObj(out,_loc11_,_loc10_,_loc6_,_loc5_,_loc3_))
            {
               _loc8_ = _loc3_;
               _loc22_ = true;
               _loc15_ = out.x;
               _loc14_ = out.y;
               break;
            }
            _loc3_ = _loc3_.next;
         }
         _loc3_ = _loc25_.next;
         while(_loc3_ != null)
         {
            if(TestRayObj(out,_loc11_,_loc10_,_loc6_,_loc5_,_loc3_))
            {
               _loc8_ = _loc3_;
               _loc23_ = true;
               _loc15_ = out.x;
               _loc14_ = out.y;
               break;
            }
            _loc3_ = _loc3_.next;
         }
         if(_loc22_ || _loc23_)
         {
            break;
         }
         if(_loc30_)
         {
            out.x = _loc27_;
            out.y = _loc26_;
            return true;
         }
         if(_loc24_)
         {
            out.x = _loc29_;
            out.y = _loc28_;
            return true;
         }
         if(_loc12_)
         {
            _loc30_ = true;
         }
         _loc2_ = _loc9_;
      }
      out.x = _loc15_;
      out.y = _loc14_;
      _loc8_.pos.x += _loc6_ * 3;
      _loc8_.pos.y += _loc5_ * 3;
      return true;
   }
   return false;
}
