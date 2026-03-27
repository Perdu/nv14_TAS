function QueryRayObj(out, p0, p1, obj)
{
   var _loc5_ = tiles.GetTile_V(p0);
   var _loc25_ = _loc5_.i;
   var _loc24_ = _loc5_.j;
   var _loc4_ = p1.x - p0.x;
   var _loc3_ = p1.y - p0.y;
   var _loc23_ = Math.sqrt(_loc4_ * _loc4_ + _loc3_ * _loc3_);
   var _loc22_;
   var _loc21_;
   var _loc18_;
   var _loc14_;
   var _loc20_;
   var _loc17_;
   var _loc13_;
   var _loc19_;
   var _loc9_;
   var _loc8_;
   var _loc11_;
   var _loc10_;
   var _loc16_;
   var _loc15_;
   var _loc6_;
   var _loc7_;
   if(_loc23_ != 0)
   {
      _loc4_ /= _loc23_;
      _loc3_ /= _loc23_;
      _loc22_ = _loc25_;
      _loc21_ = _loc24_;
      if(_loc4_ < 0)
      {
         _loc18_ = -1;
         _loc14_ = (_loc5_.pos.x - _loc5_.xw - p0.x) / _loc4_;
         _loc20_ = 2 * _loc5_.xw / (- _loc4_);
      }
      else if(0 < _loc4_)
      {
         _loc18_ = 1;
         _loc14_ = (_loc5_.pos.x + _loc5_.xw - p0.x) / _loc4_;
         _loc20_ = 2 * _loc5_.xw / _loc4_;
      }
      else
      {
         _loc18_ = 0;
         _loc14_ = 100000000;
         _loc20_ = 0;
      }
      if(_loc3_ < 0)
      {
         _loc17_ = -1;
         _loc13_ = (_loc5_.pos.y - _loc5_.yw - p0.y) / _loc3_;
         _loc19_ = 2 * _loc5_.yw / (- _loc3_);
      }
      else if(0 < _loc3_)
      {
         _loc17_ = 1;
         _loc13_ = (_loc5_.pos.y + _loc5_.yw - p0.y) / _loc3_;
         _loc19_ = 2 * _loc5_.yw / _loc3_;
      }
      else
      {
         _loc17_ = 0;
         _loc13_ = 100000000;
         _loc19_ = 0;
      }
      _loc9_ = p0.x;
      _loc8_ = p0.y;
      if(TestRayTile(out,_loc9_,_loc8_,_loc4_,_loc3_,_loc5_))
      {
         _loc11_ = out.x;
         _loc10_ = out.y;
         if(TestRay_Circle(out,p0.x,p0.y,_loc4_,_loc3_,obj))
         {
            _loc16_ = (p0.x - out.x) * _loc4_ + (p0.y - out.y) * _loc3_;
            _loc15_ = (p0.x - _loc11_) * _loc4_ + (p0.y - _loc10_) * _loc3_;
            if(_loc16_ < _loc15_)
            {
               out.x = _loc11_;
               out.y = _loc10_;
               return false;
            }
            return true;
         }
         out.x = _loc11_;
         out.y = _loc10_;
         return false;
      }
      while(_loc5_ != null)
      {
         if(_loc14_ < _loc13_)
         {
            if(_loc18_ < 0)
            {
               _loc6_ = _loc5_.eL;
               _loc7_ = _loc5_.nL;
            }
            else
            {
               _loc6_ = _loc5_.eR;
               _loc7_ = _loc5_.nR;
            }
            if(0 < _loc6_)
            {
               _loc9_ = p0.x + _loc14_ * _loc4_;
               _loc8_ = p0.y + _loc14_ * _loc3_;
               if(_loc6_ == EID_SOLID)
               {
                  _loc11_ = _loc9_;
                  _loc10_ = _loc8_;
                  if(TestRay_Circle(out,p0.x,p0.y,_loc4_,_loc3_,obj))
                  {
                     _loc16_ = (p0.x - out.x) * _loc4_ + (p0.y - out.y) * _loc3_;
                     _loc15_ = (p0.x - _loc11_) * _loc4_ + (p0.y - _loc10_) * _loc3_;
                     if(_loc16_ < _loc15_)
                     {
                        out.x = _loc11_;
                        out.y = _loc10_;
                        return false;
                     }
                     return true;
                  }
                  out.x = _loc11_;
                  out.y = _loc10_;
                  return false;
               }
               if(TestRayTile(out,_loc9_,_loc8_,_loc4_,_loc3_,_loc7_))
               {
                  _loc11_ = out.x;
                  _loc10_ = out.y;
                  if(TestRay_Circle(out,p0.x,p0.y,_loc4_,_loc3_,obj))
                  {
                     _loc16_ = (p0.x - out.x) * _loc4_ + (p0.y - out.y) * _loc3_;
                     _loc15_ = (p0.x - _loc11_) * _loc4_ + (p0.y - _loc10_) * _loc3_;
                     if(_loc16_ < _loc15_)
                     {
                        out.x = _loc11_;
                        out.y = _loc10_;
                        return false;
                     }
                     return true;
                  }
                  out.x = _loc11_;
                  out.y = _loc10_;
                  return false;
               }
            }
            _loc14_ += _loc20_;
            _loc22_ += _loc18_;
         }
         else
         {
            if(_loc17_ < 0)
            {
               _loc6_ = _loc5_.eU;
               _loc7_ = _loc5_.nU;
            }
            else
            {
               _loc6_ = _loc5_.eD;
               _loc7_ = _loc5_.nD;
            }
            if(0 < _loc6_)
            {
               _loc9_ = p0.x + _loc13_ * _loc4_;
               _loc8_ = p0.y + _loc13_ * _loc3_;
               if(_loc6_ == EID_SOLID)
               {
                  _loc11_ = _loc9_;
                  _loc10_ = _loc8_;
                  if(TestRay_Circle(out,p0.x,p0.y,_loc4_,_loc3_,obj))
                  {
                     _loc16_ = (p0.x - out.x) * _loc4_ + (p0.y - out.y) * _loc3_;
                     _loc15_ = (p0.x - _loc11_) * _loc4_ + (p0.y - _loc10_) * _loc3_;
                     if(_loc16_ < _loc15_)
                     {
                        out.x = _loc11_;
                        out.y = _loc10_;
                        return false;
                     }
                     return true;
                  }
                  out.x = _loc11_;
                  out.y = _loc10_;
                  return false;
               }
               if(TestRayTile(out,_loc9_,_loc8_,_loc4_,_loc3_,_loc7_))
               {
                  _loc11_ = out.x;
                  _loc10_ = out.y;
                  if(TestRay_Circle(out,p0.x,p0.y,_loc4_,_loc3_,obj))
                  {
                     _loc16_ = (p0.x - out.x) * _loc4_ + (p0.y - out.y) * _loc3_;
                     _loc15_ = (p0.x - _loc11_) * _loc4_ + (p0.y - _loc10_) * _loc3_;
                     if(_loc16_ < _loc15_)
                     {
                        out.x = _loc11_;
                        out.y = _loc10_;
                        return false;
                     }
                     return true;
                  }
                  out.x = _loc11_;
                  out.y = _loc10_;
                  return false;
               }
            }
            _loc13_ += _loc19_;
            _loc21_ += _loc17_;
         }
         _loc5_ = _loc7_;
      }
      if(TestRay_Circle(out,p0.x,p0.y,_loc4_,_loc3_,obj))
      {
         return true;
      }
      return false;
   }
   return false;
}
