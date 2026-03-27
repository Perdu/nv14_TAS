function TestRay_Convex(out, px, py, dx, dy, t)
{
   var _loc17_ = t.signx;
   var _loc16_ = t.signy;
   var _loc9_ = px - (t.pos.x - _loc17_ * t.xw);
   var _loc8_ = py - (t.pos.y - _loc16_ * t.yw);
   var _loc11_ = dx * dx + dy * dy;
   var _loc2_ = 2 * (dx * _loc9_ + dy * _loc8_);
   var _loc12_ = t.xw * 2;
   var _loc15_ = _loc9_ * _loc9_ + _loc8_ * _loc8_ - _loc12_ * _loc12_;
   var _loc7_ = _loc2_ * _loc2_ - 4 * _loc11_ * _loc15_;
   var _loc14_;
   var _loc10_;
   var _loc4_;
   var _loc3_;
   if(0 <= _loc7_)
   {
      _loc14_ = Math.sqrt(_loc7_);
      _loc10_ = 1 / (2 * _loc11_);
      _loc4_ = (- _loc2_ + _loc14_) * _loc10_;
      _loc3_ = (- _loc2_ - _loc14_) * _loc10_;
      if(_loc3_ < _loc4_)
      {
         out.x = px + _loc3_ * dx;
         out.y = py + _loc3_ * dy;
      }
      else
      {
         out.x = px + _loc4_ * dx;
         out.y = py + _loc4_ * dy;
      }
      return true;
   }
   return false;
}
