function TestRay_Half(out, px, py, dx, dy, t)
{
   var _loc4_ = t.signx;
   var _loc3_ = t.signy;
   var _loc6_ = t.pos.x - px;
   var _loc5_ = t.pos.y - py;
   if(0 <= _loc6_ * _loc4_ + _loc5_ * _loc3_)
   {
      out.x = px;
      out.y = py;
      return true;
   }
   if(0 <= _loc4_ * dx + _loc3_ * dy)
   {
      return false;
   }
   var _loc8_ = _loc3_ * t.xw;
   var _loc7_ = _loc4_ * t.yw;
   var _loc2_ = (dy * _loc6_ - dx * _loc5_) / (dx * _loc7_ - dy * _loc8_);
   if(Math.abs(_loc2_) <= 1)
   {
      out.x = t.pos.x + _loc2_ * _loc8_;
      out.y = t.pos.y + _loc2_ * _loc7_;
      return true;
   }
   return false;
}
