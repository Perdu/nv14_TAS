function ProjCircle_Convex(x, y, oH, oV, obj, t)
{
   var _loc7_ = t.signx;
   var _loc6_ = t.signy;
   var _loc9_;
   var _loc8_;
   var _loc15_;
   var _loc18_;
   var _loc13_;
   var _loc14_;
   var _loc17_;
   var _loc16_;
   var _loc4_;
   var _loc3_;
   if(oH == 0)
   {
      if(oV == 0)
      {
         _loc9_ = obj.pos.x - (t.pos.x - _loc7_ * t.xw);
         _loc8_ = obj.pos.y - (t.pos.y - _loc6_ * t.yw);
         _loc15_ = t.xw * 2;
         _loc18_ = Math.sqrt(_loc15_ * _loc15_ + 0);
         _loc13_ = Math.sqrt(_loc9_ * _loc9_ + _loc8_ * _loc8_);
         _loc14_ = _loc18_ + obj.r - _loc13_;
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
            _loc9_ /= _loc13_;
            _loc8_ /= _loc13_;
            obj.ReportCollisionVsWorld(_loc9_ * _loc14_,_loc8_ * _loc14_,_loc9_,_loc8_,t);
            return COL_OTHER;
         }
      }
      else
      {
         if(_loc6_ * oV < 0)
         {
            obj.ReportCollisionVsWorld(0,y * oV,0,oV,t);
            return COL_AXIS;
         }
         _loc9_ = obj.pos.x - (t.pos.x - _loc7_ * t.xw);
         _loc8_ = obj.pos.y - (t.pos.y - _loc6_ * t.yw);
         _loc15_ = t.xw * 2;
         _loc18_ = Math.sqrt(_loc15_ * _loc15_ + 0);
         _loc13_ = Math.sqrt(_loc9_ * _loc9_ + _loc8_ * _loc8_);
         _loc14_ = _loc18_ + obj.r - _loc13_;
         if(0 < _loc14_)
         {
            _loc9_ /= _loc13_;
            _loc8_ /= _loc13_;
            obj.ReportCollisionVsWorld(_loc9_ * _loc14_,_loc8_ * _loc14_,_loc9_,_loc8_,t);
            return COL_OTHER;
         }
      }
   }
   else if(oV == 0)
   {
      if(_loc7_ * oH < 0)
      {
         obj.ReportCollisionVsWorld(x * oH,0,oH,0,t);
         return COL_AXIS;
      }
      _loc9_ = obj.pos.x - (t.pos.x - _loc7_ * t.xw);
      _loc8_ = obj.pos.y - (t.pos.y - _loc6_ * t.yw);
      _loc15_ = t.xw * 2;
      _loc18_ = Math.sqrt(_loc15_ * _loc15_ + 0);
      _loc13_ = Math.sqrt(_loc9_ * _loc9_ + _loc8_ * _loc8_);
      _loc14_ = _loc18_ + obj.r - _loc13_;
      if(0 < _loc14_)
      {
         _loc9_ /= _loc13_;
         _loc8_ /= _loc13_;
         obj.ReportCollisionVsWorld(_loc9_ * _loc14_,_loc8_ * _loc14_,_loc9_,_loc8_,t);
         return COL_OTHER;
      }
   }
   else if(0 < _loc7_ * oH + _loc6_ * oV)
   {
      _loc9_ = obj.pos.x - (t.pos.x - _loc7_ * t.xw);
      _loc8_ = obj.pos.y - (t.pos.y - _loc6_ * t.yw);
      _loc15_ = t.xw * 2;
      _loc18_ = Math.sqrt(_loc15_ * _loc15_ + 0);
      _loc13_ = Math.sqrt(_loc9_ * _loc9_ + _loc8_ * _loc8_);
      _loc14_ = _loc18_ + obj.r - _loc13_;
      if(0 < _loc14_)
      {
         _loc9_ /= _loc13_;
         _loc8_ /= _loc13_;
         obj.ReportCollisionVsWorld(_loc9_ * _loc14_,_loc8_ * _loc14_,_loc9_,_loc8_,t);
         return COL_OTHER;
      }
   }
   else
   {
      _loc17_ = t.pos.x + oH * t.xw;
      _loc16_ = t.pos.y + oV * t.yw;
      _loc4_ = obj.pos.x - _loc17_;
      _loc3_ = obj.pos.y - _loc16_;
      _loc13_ = Math.sqrt(_loc4_ * _loc4_ + _loc3_ * _loc3_);
      _loc14_ = obj.r - _loc13_;
      if(0 < _loc14_)
      {
         if(_loc13_ == 0)
         {
            _loc4_ = oH / 1.4142135623730951;
            _loc3_ = oV / 1.4142135623730951;
         }
         else
         {
            _loc4_ /= _loc13_;
            _loc3_ /= _loc13_;
         }
         obj.ReportCollisionVsWorld(_loc4_ * _loc14_,_loc3_ * _loc14_,_loc4_,_loc3_,t);
         return COL_OTHER;
      }
   }
   return COL_NONE;
}
