function ProjCircle_Half(x, y, oH, oV, obj, t)
{
   var _loc7_ = t.signx;
   var _loc13_ = t.signy;
   var _loc17_ = oH * _loc7_ + oV * _loc13_;
   if(0 < _loc17_)
   {
      return COL_NONE;
   }
   var _loc23_;
   var _loc21_;
   var _loc20_;
   var _loc9_;
   var _loc8_;
   var _loc16_;
   var _loc22_;
   var _loc15_;
   var _loc6_;
   var _loc5_;
   var _loc10_;
   var _loc14_;
   var _loc19_;
   var _loc18_;
   if(oH == 0)
   {
      if(oV == 0)
      {
         _loc23_ = obj.r;
         _loc21_ = obj.pos.x - _loc7_ * _loc23_ - t.pos.x;
         _loc20_ = obj.pos.y - _loc13_ * _loc23_ - t.pos.y;
         _loc9_ = _loc7_;
         _loc8_ = _loc13_;
         _loc16_ = _loc21_ * _loc9_ + _loc20_ * _loc8_;
         if(_loc16_ < 0)
         {
            _loc9_ *= - _loc16_;
            _loc8_ *= - _loc16_;
            _loc22_ = Math.sqrt(_loc9_ * _loc9_ + _loc8_ * _loc8_);
            _loc15_ = Math.sqrt(x * x + y * y);
            if(_loc15_ < _loc22_)
            {
               obj.ReportCollisionVsWorld(x,y,x / _loc15_,y / _loc15_,t);
               return COL_AXIS;
            }
            obj.ReportCollisionVsWorld(_loc9_,_loc8_,t.signx,t.signy);
            return COL_OTHER;
         }
      }
      else
      {
         if(_loc17_ != 0)
         {
            obj.ReportCollisionVsWorld(0,y * oV,0,oV,t);
            return COL_AXIS;
         }
         _loc23_ = obj.r;
         _loc6_ = obj.pos.x - t.pos.x;
         if(_loc6_ * _loc7_ < 0)
         {
            obj.ReportCollisionVsWorld(0,y * oV,0,oV,t);
            return COL_AXIS;
         }
         _loc5_ = obj.pos.y - (t.pos.y + oV * t.yw);
         _loc10_ = Math.sqrt(_loc6_ * _loc6_ + _loc5_ * _loc5_);
         _loc14_ = obj.r - _loc10_;
         if(0 < _loc14_)
         {
            if(_loc10_ == 0)
            {
               _loc6_ = _loc7_ / 1.4142135623730951;
               _loc5_ = oV / 1.4142135623730951;
            }
            else
            {
               _loc6_ /= _loc10_;
               _loc5_ /= _loc10_;
            }
            obj.ReportCollisionVsWorld(_loc6_ * _loc14_,_loc5_ * _loc14_,_loc6_,_loc5_,t);
            return COL_OTHER;
         }
      }
   }
   else if(oV == 0)
   {
      if(_loc17_ != 0)
      {
         obj.ReportCollisionVsWorld(x * oH,0,oH,0,t);
         return COL_AXIS;
      }
      _loc23_ = obj.r;
      _loc5_ = obj.pos.y - t.pos.y;
      if(_loc5_ * _loc13_ < 0)
      {
         obj.ReportCollisionVsWorld(x * oH,0,oH,0,t);
         return COL_AXIS;
      }
      _loc6_ = obj.pos.x - (t.pos.x + oH * t.xw);
      _loc10_ = Math.sqrt(_loc6_ * _loc6_ + _loc5_ * _loc5_);
      _loc14_ = obj.r - _loc10_;
      if(0 < _loc14_)
      {
         if(_loc10_ == 0)
         {
            _loc6_ = _loc7_ / 1.4142135623730951;
            _loc5_ = oV / 1.4142135623730951;
         }
         else
         {
            _loc6_ /= _loc10_;
            _loc5_ /= _loc10_;
         }
         obj.ReportCollisionVsWorld(_loc6_ * _loc14_,_loc5_ * _loc14_,_loc6_,_loc5_,t);
         return COL_OTHER;
      }
   }
   else
   {
      _loc19_ = t.pos.x + oH * t.xw;
      _loc18_ = t.pos.y + oV * t.yw;
      _loc6_ = obj.pos.x - _loc19_;
      _loc5_ = obj.pos.y - _loc18_;
      _loc10_ = Math.sqrt(_loc6_ * _loc6_ + _loc5_ * _loc5_);
      _loc14_ = obj.r - _loc10_;
      if(0 < _loc14_)
      {
         if(_loc10_ == 0)
         {
            _loc6_ = oH / 1.4142135623730951;
            _loc5_ = oV / 1.4142135623730951;
         }
         else
         {
            _loc6_ /= _loc10_;
            _loc5_ /= _loc10_;
         }
         obj.ReportCollisionVsWorld(_loc6_ * _loc14_,_loc5_ * _loc14_,_loc6_,_loc5_,t);
         return COL_OTHER;
      }
   }
   return COL_NONE;
}
