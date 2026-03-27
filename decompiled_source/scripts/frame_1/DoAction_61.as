function TestRay_22DegS(out, px, py, dx, dy, t)
{
   var _loc14_ = t.sx;
   var _loc12_ = t.sy;
   var _loc3_ = t.signx;
   var _loc6_ = t.signy;
   var _loc5_ = t.pos.x - _loc3_ * t.xw - px;
   var _loc4_ = t.pos.y - py;
   if(0 <= _loc5_ * _loc3_ && 0 <= _loc4_ * _loc6_)
   {
      out.x = px;
      out.y = py;
      return true;
   }
   if(0 <= _loc14_ * dx + _loc12_ * dy)
   {
      return false;
   }
   _loc5_ += _loc3_ * t.xw;
   var _loc7_ = _loc6_ * 0.5 * t.yw;
   _loc4_ -= _loc7_;
   var _loc9_ = (- _loc6_) * t.xw;
   var _loc8_ = 0.5 * _loc3_ * t.yw;
   var _loc2_ = (dy * _loc5_ - dx * _loc4_) / (dx * _loc8_ - dy * _loc9_);
   if(Math.abs(_loc2_) <= 1)
   {
      out.x = t.pos.x + _loc2_ * _loc9_;
      out.y = t.pos.y - _loc7_ + _loc2_ * _loc8_;
      return true;
   }
   return false;
}
