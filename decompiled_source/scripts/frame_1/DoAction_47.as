function ProjCircle_22DegB(x, y, oH, oV, obj, t)
{
   var _loc4_ = t.signx;
   var _loc3_ = t.signy;
   var _loc13_;
   var _loc12_;
   var _loc16_;
   var _loc22_;
   var _loc21_;
   var _loc15_;
   var _loc23_;
   var _loc18_;
   var _loc11_;
   var _loc14_;
   var _loc17_;
   var _loc20_;
   var _loc19_;
   var _loc7_;
   var _loc6_;
   if(oH == 0)
   {
      if(oV == 0)
      {
         _loc13_ = t.sx;
         _loc12_ = t.sy;
         _loc16_ = obj.r;
         _loc22_ = obj.pos.x - _loc13_ * _loc16_ - (t.pos.x - _loc4_ * t.xw);
         _loc21_ = obj.pos.y - _loc12_ * _loc16_ - (t.pos.y + _loc3_ * t.yw);
         _loc15_ = _loc22_ * _loc13_ + _loc21_ * _loc12_;
         if(_loc15_ < 0)
         {
            _loc13_ *= - _loc15_;
            _loc12_ *= - _loc15_;
            _loc23_ = Math.sqrt(_loc13_ * _loc13_ + _loc12_ * _loc12_);
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
            if(lenP < _loc23_)
            {
               obj.ReportCollisionVsWorld(x,y,x / lenP,y / lenP,t);
               return COL_AXIS;
            }
            obj.ReportCollisionVsWorld(_loc13_,_loc12_,t.sx,t.sy,t);
            return COL_OTHER;
         }
      }
      else
      {
         if(_loc3_ * oV < 0)
         {
            obj.ReportCollisionVsWorld(0,y * oV,0,oV,t);
            return COL_AXIS;
         }
         _loc13_ = t.sx;
         _loc12_ = t.sy;
         _loc22_ = obj.pos.x - (t.pos.x - _loc4_ * t.xw);
         _loc21_ = obj.pos.y - (t.pos.y + _loc3_ * t.yw);
         _loc18_ = _loc22_ * (- _loc12_) + _loc21_ * _loc13_;
         if(0 < _loc18_ * _loc4_ * _loc3_)
         {
            _loc11_ = Math.sqrt(_loc22_ * _loc22_ + _loc21_ * _loc21_);
            _loc14_ = obj.r - _loc11_;
            if(0 < _loc14_)
            {
               _loc22_ /= _loc11_;
               _loc21_ /= _loc11_;
               obj.ReportCollisionVsWorld(_loc22_ * _loc14_,_loc21_ * _loc14_,_loc22_,_loc21_,t);
               return COL_OTHER;
            }
         }
         else
         {
            _loc15_ = _loc22_ * _loc13_ + _loc21_ * _loc12_;
            _loc14_ = obj.r - Math.abs(_loc15_);
            if(0 < _loc14_)
            {
               obj.ReportCollisionVsWorld(_loc13_ * _loc14_,_loc12_ * _loc14_,_loc13_,_loc12_,t);
               return COL_OTHER;
            }
         }
      }
   }
   else if(oV == 0)
   {
      if(_loc4_ * oH < 0)
      {
         obj.ReportCollisionVsWorld(x * oH,0,oH,0,t);
         return COL_AXIS;
      }
      _loc22_ = obj.pos.x - (t.pos.x + _loc4_ * t.xw);
      _loc21_ = obj.pos.y - t.pos.y;
      if(_loc21_ * _loc3_ < 0)
      {
         obj.ReportCollisionVsWorld(x * oH,0,oH,0,t);
         return COL_AXIS;
      }
      _loc13_ = t.sx;
      _loc12_ = t.sy;
      _loc18_ = _loc22_ * (- _loc12_) + _loc21_ * _loc13_;
      if(_loc18_ * _loc4_ * _loc3_ < 0)
      {
         _loc11_ = Math.sqrt(_loc22_ * _loc22_ + _loc21_ * _loc21_);
         _loc14_ = obj.r - _loc11_;
         if(0 < _loc14_)
         {
            _loc22_ /= _loc11_;
            _loc21_ /= _loc11_;
            obj.ReportCollisionVsWorld(_loc22_ * _loc14_,_loc21_ * _loc14_,_loc22_,_loc21_,t);
            return COL_OTHER;
         }
      }
      else
      {
         _loc15_ = _loc22_ * _loc13_ + _loc21_ * _loc12_;
         _loc14_ = obj.r - Math.abs(_loc15_);
         if(0 < _loc14_)
         {
            obj.ReportCollisionVsWorld(_loc13_ * _loc14_,_loc12_ * _loc14_,t.sx,t.sy,t);
            return COL_OTHER;
         }
      }
   }
   else
   {
      if(0 < _loc4_ * oH + _loc3_ * oV)
      {
         _loc17_ = 2.23606797749979;
         _loc13_ = _loc4_ * 1 / _loc17_;
         _loc12_ = _loc3_ * 2 / _loc17_;
         _loc16_ = obj.r;
         _loc22_ = obj.pos.x - _loc13_ * _loc16_ - (t.pos.x - _loc4_ * t.xw);
         _loc21_ = obj.pos.y - _loc12_ * _loc16_ - (t.pos.y + _loc3_ * t.yw);
         _loc15_ = _loc22_ * _loc13_ + _loc21_ * _loc12_;
         if(_loc15_ < 0)
         {
            obj.ReportCollisionVsWorld((- _loc13_) * _loc15_,(- _loc12_) * _loc15_,t.sx,t.sy,t);
            return COL_OTHER;
         }
         return COL_NONE;
      }
      _loc20_ = t.pos.x + oH * t.xw;
      _loc19_ = t.pos.y + oV * t.yw;
      _loc7_ = obj.pos.x - _loc20_;
      _loc6_ = obj.pos.y - _loc19_;
      _loc11_ = Math.sqrt(_loc7_ * _loc7_ + _loc6_ * _loc6_);
      _loc14_ = obj.r - _loc11_;
      if(0 < _loc14_)
      {
         if(_loc11_ == 0)
         {
            _loc7_ = oH / 1.4142135623730951;
            _loc6_ = oV / 1.4142135623730951;
         }
         else
         {
            _loc7_ /= _loc11_;
            _loc6_ /= _loc11_;
         }
         obj.ReportCollisionVsWorld(_loc7_ * _loc14_,_loc6_ * _loc14_,_loc7_,_loc6_,t);
         return COL_OTHER;
      }
   }
   return COL_NONE;
}
