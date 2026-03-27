function TestRay_Concave(out, px, py, dx, dy, t)
{
   var _loc17_ = t.signx;
   var _loc15_ = t.signy;
   if(0 <= _loc17_ * dx + _loc15_ * dy)
   {
      return false;
   }
   var _loc13_ = _loc17_ * t.xw;
   var _loc12_ = (- _loc15_) * t.yw;
   var _loc10_ = t.pos.x - px;
   var _loc9_ = t.pos.y - py;
   var _loc14_ = (dy * _loc10_ - dx * _loc9_) / (dx * _loc12_ - dy * _loc13_);
   var _loc6_;
   var _loc5_;
   var _loc16_;
   var _loc4_;
   var _loc18_;
   var _loc22_;
   var _loc19_;
   var _loc21_;
   var _loc11_;
   var _loc8_;
   var _loc7_;
   if(Math.abs(_loc14_) <= 1)
   {
      _loc6_ = - _loc13_ - _loc10_;
      _loc5_ = _loc12_ - _loc9_;
      _loc16_ = dx * dx + dy * dy;
      _loc4_ = 2 * (dx * _loc6_ + dy * _loc5_);
      _loc18_ = t.xw * 2;
      _loc22_ = _loc6_ * _loc6_ + _loc5_ * _loc5_ - _loc18_ * _loc18_;
      _loc19_ = _loc4_ * _loc4_ - 4 * _loc16_ * _loc22_;
      if(0 <= _loc19_)
      {
         _loc21_ = Math.sqrt(_loc19_);
         _loc11_ = 1 / (2 * _loc16_);
         _loc8_ = (- _loc4_ + _loc21_) * _loc11_;
         _loc7_ = (- _loc4_ - _loc21_) * _loc11_;
         if(_loc7_ < _loc8_)
         {
            out.x = px + _loc8_ * dx;
            out.y = py + _loc8_ * dy;
         }
         else
         {
            out.x = px + _loc7_ * dx;
            out.y = py + _loc7_ * dy;
         }
         return true;
      }
      return false;
   }
   return false;
}
