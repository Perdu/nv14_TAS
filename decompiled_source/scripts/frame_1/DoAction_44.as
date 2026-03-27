function ProjCircle_Concave(x, y, oH, oV, obj, t)
{
   var _loc13_ = t.signx;
   var _loc12_ = t.signy;
   var _loc8_;
   var _loc7_;
   var _loc15_;
   var _loc18_;
   var _loc11_;
   var _loc14_;
   var _loc17_;
   var _loc16_;
   var _loc6_;
   var _loc5_;
   if(oH == 0)
   {
      if(oV == 0)
      {
         _loc8_ = t.pos.x + _loc13_ * t.xw - obj.pos.x;
         _loc7_ = t.pos.y + _loc12_ * t.yw - obj.pos.y;
         _loc15_ = t.xw * 2;
         _loc18_ = Math.sqrt(_loc15_ * _loc15_ + 0);
         _loc11_ = Math.sqrt(_loc8_ * _loc8_ + _loc7_ * _loc7_);
         _loc14_ = _loc11_ + obj.r - _loc18_;
         if(0 < _loc14_)
         {
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
            if(lenP < _loc14_)
            {
               obj.ReportCollisionVsWorld(x,y,x / lenP,y / lenP,t);
               return COL_AXIS;
            }
            _loc8_ /= _loc11_;
            _loc7_ /= _loc11_;
            obj.ReportCollisionVsWorld(_loc8_ * _loc14_,_loc7_ * _loc14_,_loc8_,_loc7_,t);
            return COL_OTHER;
         }
         return COL_NONE;
      }
      if(_loc12_ * oV < 0)
      {
         obj.ReportCollisionVsWorld(0,y * oV,0,oV,t);
         return COL_AXIS;
      }
      _loc17_ = t.pos.x - _loc13_ * t.xw;
      _loc16_ = t.pos.y + oV * t.yw;
      _loc6_ = obj.pos.x - _loc17_;
      _loc5_ = obj.pos.y - _loc16_;
      _loc11_ = Math.sqrt(_loc6_ * _loc6_ + _loc5_ * _loc5_);
      _loc14_ = obj.r - _loc11_;
      if(0 < _loc14_)
      {
         if(_loc11_ == 0)
         {
            _loc6_ = 0;
            _loc5_ = oV;
         }
         else
         {
            _loc6_ /= _loc11_;
            _loc5_ /= _loc11_;
         }
         obj.ReportCollisionVsWorld(_loc6_ * _loc14_,_loc5_ * _loc14_,_loc6_,_loc5_,t);
         return COL_OTHER;
      }
   }
   else if(oV == 0)
   {
      if(_loc13_ * oH < 0)
      {
         obj.ReportCollisionVsWorld(x * oH,0,oH,0,t);
         return COL_AXIS;
      }
      _loc17_ = t.pos.x + oH * t.xw;
      _loc16_ = t.pos.y - _loc12_ * t.yw;
      _loc6_ = obj.pos.x - _loc17_;
      _loc5_ = obj.pos.y - _loc16_;
      _loc11_ = Math.sqrt(_loc6_ * _loc6_ + _loc5_ * _loc5_);
      _loc14_ = obj.r - _loc11_;
      if(0 < _loc14_)
      {
         if(_loc11_ == 0)
         {
            _loc6_ = oH;
            _loc5_ = 0;
         }
         else
         {
            _loc6_ /= _loc11_;
            _loc5_ /= _loc11_;
         }
         obj.ReportCollisionVsWorld(_loc6_ * _loc14_,_loc5_ * _loc14_,_loc6_,_loc5_,t);
         return COL_OTHER;
      }
   }
   else
   {
      if(0 < _loc13_ * oH + _loc12_ * oV)
      {
         return COL_NONE;
      }
      _loc17_ = t.pos.x + oH * t.xw;
      _loc16_ = t.pos.y + oV * t.yw;
      _loc6_ = obj.pos.x - _loc17_;
      _loc5_ = obj.pos.y - _loc16_;
      _loc11_ = Math.sqrt(_loc6_ * _loc6_ + _loc5_ * _loc5_);
      _loc14_ = obj.r - _loc11_;
      if(0 < _loc14_)
      {
         if(_loc11_ == 0)
         {
            _loc6_ = oH / 1.4142135623730951;
            _loc5_ = oV / 1.4142135623730951;
         }
         else
         {
            _loc6_ /= _loc11_;
            _loc5_ /= _loc11_;
         }
         obj.ReportCollisionVsWorld(_loc6_ * _loc14_,_loc5_ * _loc14_,_loc6_,_loc5_,t);
         return COL_OTHER;
      }
   }
   return COL_NONE;
}
