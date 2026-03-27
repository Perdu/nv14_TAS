function ProjCircle_22DegS(x, y, oH, oV, obj, t)
{
   var _loc12_ = t.signx;
   var _loc11_ = t.signy;
   if(0 < _loc11_ * oV)
   {
      return COL_NONE;
   }
   var _loc15_;
   var _loc14_;
   var _loc16_;
   var _loc4_;
   var _loc3_;
   var _loc18_;
   var _loc13_;
   var _loc17_;
   var _loc22_;
   var _loc21_;
   var _loc20_;
   var _loc19_;
   var _loc6_;
   var _loc5_;
   if(oH == 0)
   {
      if(oV != 0)
      {
         obj.ReportCollisionVsWorld(0,y * oV,0,oV,t);
         return COL_AXIS;
      }
      _loc15_ = t.sx;
      _loc14_ = t.sy;
      _loc16_ = obj.r;
      _loc4_ = obj.pos.x - (t.pos.x - _loc12_ * t.xw);
      _loc3_ = obj.pos.y - t.pos.y;
      _loc18_ = _loc4_ * (- _loc14_) + _loc3_ * _loc15_;
      if(0 < _loc18_ * _loc12_ * _loc11_)
      {
         _loc13_ = Math.sqrt(_loc4_ * _loc4_ + _loc3_ * _loc3_);
         _loc17_ = _loc16_ - _loc13_;
         if(0 < _loc17_)
         {
            _loc4_ /= _loc13_;
            _loc3_ /= _loc13_;
            obj.ReportCollisionVsWorld(_loc4_ * _loc17_,_loc3_ * _loc17_,_loc4_,_loc3_,t);
            return COL_OTHER;
         }
      }
      else
      {
         _loc4_ -= _loc16_ * _loc15_;
         _loc3_ -= _loc16_ * _loc14_;
         _loc22_ = _loc4_ * _loc15_ + _loc3_ * _loc14_;
         if(_loc22_ < 0)
         {
            _loc15_ *= - _loc22_;
            _loc14_ *= - _loc22_;
            _loc21_ = Math.sqrt(_loc15_ * _loc15_ + _loc14_ * _loc14_);
            if(x < y)
            {
               lenP = x;
               y = 0;
               if(obj.pos.x - t.pos.x < 0)
               {
                  x *= -1;
               }
            }
            else
            {
               lenP = y;
               x = 0;
               if(obj.pos.y - t.pos.y < 0)
               {
                  y *= -1;
               }
            }
            if(lenP < _loc21_)
            {
               obj.ReportCollisionVsWorld(x,y,x / lenP,y / lenP,t);
               return COL_AXIS;
            }
            obj.ReportCollisionVsWorld(_loc15_,_loc14_,t.sx,t.sy,t);
            return COL_OTHER;
         }
      }
   }
   else if(oV == 0)
   {
      if(_loc12_ * oH < 0)
      {
         _loc20_ = t.pos.x - _loc12_ * t.xw;
         _loc19_ = t.pos.y;
         _loc6_ = obj.pos.x - _loc20_;
         _loc5_ = obj.pos.y - _loc19_;
         if(_loc5_ * _loc11_ < 0)
         {
            obj.ReportCollisionVsWorld(x * oH,0,oH,0,t);
            return COL_AXIS;
         }
         _loc13_ = Math.sqrt(_loc6_ * _loc6_ + _loc5_ * _loc5_);
         _loc17_ = obj.r - _loc13_;
         if(0 < _loc17_)
         {
            if(_loc13_ == 0)
            {
               _loc6_ = oH / 1.4142135623730951;
               _loc5_ = oV / 1.4142135623730951;
            }
            else
            {
               _loc6_ /= _loc13_;
               _loc5_ /= _loc13_;
            }
            obj.ReportCollisionVsWorld(_loc6_ * _loc17_,_loc5_ * _loc17_,_loc6_,_loc5_,t);
            return COL_OTHER;
         }
      }
      else
      {
         _loc15_ = t.sx;
         _loc14_ = t.sy;
         _loc4_ = obj.pos.x - (t.pos.x + oH * t.xw);
         _loc3_ = obj.pos.y - (t.pos.y - _loc11_ * t.yw);
         _loc18_ = _loc4_ * (- _loc14_) + _loc3_ * _loc15_;
         if(_loc18_ * _loc12_ * _loc11_ < 0)
         {
            _loc13_ = Math.sqrt(_loc4_ * _loc4_ + _loc3_ * _loc3_);
            _loc17_ = obj.r - _loc13_;
            if(0 < _loc17_)
            {
               _loc4_ /= _loc13_;
               _loc3_ /= _loc13_;
               obj.ReportCollisionVsWorld(_loc4_ * _loc17_,_loc3_ * _loc17_,_loc4_,_loc3_,t);
               return COL_OTHER;
            }
         }
         else
         {
            _loc22_ = _loc4_ * _loc15_ + _loc3_ * _loc14_;
            _loc17_ = obj.r - Math.abs(_loc22_);
            if(0 < _loc17_)
            {
               obj.ReportCollisionVsWorld(_loc15_ * _loc17_,_loc14_ * _loc17_,_loc15_,_loc14_,t);
               return COL_OTHER;
            }
         }
      }
   }
   else
   {
      _loc20_ = t.pos.x + oH * t.xw;
      _loc19_ = t.pos.y + oV * t.yw;
      _loc6_ = obj.pos.x - _loc20_;
      _loc5_ = obj.pos.y - _loc19_;
      _loc13_ = Math.sqrt(_loc6_ * _loc6_ + _loc5_ * _loc5_);
      _loc17_ = obj.r - _loc13_;
      if(0 < _loc17_)
      {
         if(_loc13_ == 0)
         {
            _loc6_ = oH / 1.4142135623730951;
            _loc5_ = oV / 1.4142135623730951;
         }
         else
         {
            _loc6_ /= _loc13_;
            _loc5_ /= _loc13_;
         }
         obj.ReportCollisionVsWorld(_loc6_ * _loc17_,_loc5_ * _loc17_,_loc6_,_loc5_,t);
         return COL_OTHER;
      }
   }
   return COL_NONE;
}
