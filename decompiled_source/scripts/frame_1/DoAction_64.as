function TestRay_67DegB(out, px, py, dx, dy, t)
{
   var _loc14_ = t.sx;
   var _loc12_ = t.sy;
   var _loc4_ = t.signx;
   var _loc10_ = t.signy;
   var _loc3_ = t.pos.x - px;
   var _loc5_ = t.pos.y - py;
   if(_loc5_ * _loc10_ <= 0 && 0 <= _loc3_ * _loc4_)
   {
      out.x = px;
      out.y = py;
      return true;
   }
   if(0 <= _loc14_ * dx + _loc12_ * dy)
   {
      return false;
   }
   var _loc6_ = _loc4_ * 0.5 * t.xw;
   _loc3_ += _loc6_;
   var _loc8_ = -0.5 * _loc10_ * t.xw;
   var _loc7_ = _loc4_ * t.yw;
   var _loc2_ = (dy * _loc3_ - dx * _loc5_) / (dx * _loc7_ - dy * _loc8_);
   if(Math.abs(_loc2_) <= 1)
   {
      out.x = t.pos.x + _loc6_ + _loc2_ * _loc8_;
      out.y = t.pos.y + _loc2_ * _loc7_;
      return true;
   }
   return false;
}
