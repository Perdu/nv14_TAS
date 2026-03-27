function ProjCircle_45Deg(x, y, oH, oV, obj, t)
{
   var _loc12_ = t.signx;
   var _loc11_ = t.signy;
   var _loc15_;
   var _loc14_;
   var _loc4_;
   var _loc3_;
   var _loc21_;
   var _loc20_;
   var _loc17_;
   var _loc13_;
   var _loc16_;
   var _loc19_;
   var _loc18_;
   var _loc7_;
   var _loc6_;
   if(oH == 0)
   {
      if(oV == 0)
      {
         _loc15_ = t.sx;
         _loc14_ = t.sy;
         _loc4_ = obj.pos.x - _loc15_ * obj.r - t.pos.x;
         _loc3_ = obj.pos.y - _loc14_ * obj.r - t.pos.y;
         _loc21_ = _loc4_ * _loc15_ + _loc3_ * _loc14_;
         if(_loc21_ < 0)
         {
            _loc15_ *= - _loc21_;
            _loc14_ *= - _loc21_;
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
            _loc20_ = Math.sqrt(_loc15_ * _loc15_ + _loc14_ * _loc14_);
            if(lenP < _loc20_)
            {
               obj.ReportCollisionVsWorld(x,y,x / lenP,y / lenP,t);
               return COL_AXIS;
            }
            obj.ReportCollisionVsWorld(_loc15_,_loc14_,t.sx,t.sy,t);
            return COL_OTHER;
         }
      }
      else
      {
         if(_loc11_ * oV < 0)
         {
            obj.ReportCollisionVsWorld(0,y * oV,0,oV,t);
            return COL_AXIS;
         }
         _loc15_ = t.sx;
         _loc14_ = t.sy;
         _loc4_ = obj.pos.x - (t.pos.x - _loc12_ * t.xw);
         _loc3_ = obj.pos.y - (t.pos.y + oV * t.yw);
         _loc17_ = _loc4_ * (- _loc14_) + _loc3_ * _loc15_;
         if(0 < _loc17_ * _loc12_ * _loc11_)
         {
            _loc13_ = Math.sqrt(_loc4_ * _loc4_ + _loc3_ * _loc3_);
            _loc16_ = obj.r - _loc13_;
            if(0 < _loc16_)
            {
               _loc4_ /= _loc13_;
               _loc3_ /= _loc13_;
               obj.ReportCollisionVsWorld(_loc4_ * _loc16_,_loc3_ * _loc16_,_loc4_,_loc3_,t);
               return COL_OTHER;
            }
         }
         else
         {
            _loc21_ = _loc4_ * _loc15_ + _loc3_ * _loc14_;
            _loc16_ = obj.r - Math.abs(_loc21_);
            if(0 < _loc16_)
            {
               obj.ReportCollisionVsWorld(_loc15_ * _loc16_,_loc14_ * _loc16_,_loc15_,_loc14_,t);
               return COL_OTHER;
            }
         }
      }
   }
   else if(oV == 0)
   {
      if(_loc12_ * oH < 0)
      {
         obj.ReportCollisionVsWorld(x * oH,0,oH,0,t);
         return COL_AXIS;
      }
      _loc15_ = t.sx;
      _loc14_ = t.sy;
      _loc4_ = obj.pos.x - (t.pos.x + oH * t.xw);
      _loc3_ = obj.pos.y - (t.pos.y - _loc11_ * t.yw);
      _loc17_ = _loc4_ * (- _loc14_) + _loc3_ * _loc15_;
      if(_loc17_ * _loc12_ * _loc11_ < 0)
      {
         _loc13_ = Math.sqrt(_loc4_ * _loc4_ + _loc3_ * _loc3_);
         _loc16_ = obj.r - _loc13_;
         if(0 < _loc16_)
         {
            _loc4_ /= _loc13_;
            _loc3_ /= _loc13_;
            obj.ReportCollisionVsWorld(_loc4_ * _loc16_,_loc3_ * _loc16_,_loc4_,_loc3_,t);
            return COL_OTHER;
         }
      }
      else
      {
         _loc21_ = _loc4_ * _loc15_ + _loc3_ * _loc14_;
         _loc16_ = obj.r - Math.abs(_loc21_);
         if(0 < _loc16_)
         {
            obj.ReportCollisionVsWorld(_loc15_ * _loc16_,_loc14_ * _loc16_,_loc15_,_loc14_,t);
            return COL_OTHER;
         }
      }
   }
   else
   {
      if(0 < _loc12_ * oH + _loc11_ * oV)
      {
         return COL_NONE;
      }
      _loc19_ = t.pos.x + oH * t.xw;
      _loc18_ = t.pos.y + oV * t.yw;
      _loc7_ = obj.pos.x - _loc19_;
      _loc6_ = obj.pos.y - _loc18_;
      _loc13_ = Math.sqrt(_loc7_ * _loc7_ + _loc6_ * _loc6_);
      _loc16_ = obj.r - _loc13_;
      if(0 < _loc16_)
      {
         if(_loc13_ == 0)
         {
            _loc7_ = oH / 1.4142135623730951;
            _loc6_ = oV / 1.4142135623730951;
         }
         else
         {
            _loc7_ /= _loc13_;
            _loc6_ /= _loc13_;
         }
         obj.ReportCollisionVsWorld(_loc7_ * _loc16_,_loc6_ * _loc16_,_loc7_,_loc6_,t);
         return COL_OTHER;
      }
   }
   return COL_NONE;
}
