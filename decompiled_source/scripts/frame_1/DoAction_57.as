function TestRay_45Deg(out, px, py, dx, dy, t)
{
   var _loc6_ = t.signx;
   var _loc5_ = t.signy;
   if(0 <= _loc6_ * dx + _loc5_ * dy)
   {
      return false;
   }
   var _loc4_ = _loc6_ * t.xw;
   var _loc3_ = (- _loc5_) * t.yw;
   var _loc8_ = t.pos.x - px;
   var _loc7_ = t.pos.y - py;
   var _loc2_ = (dy * _loc8_ - dx * _loc7_) / (dx * _loc3_ - dy * _loc4_);
   if(Math.abs(_loc2_) <= 1)
   {
      out.x = t.pos.x + _loc2_ * _loc4_;
      out.y = t.pos.y + _loc2_ * _loc3_;
      return true;
   }
   return false;
}
