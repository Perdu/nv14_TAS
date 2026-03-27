function TestRay_Circle(out, px, py, dx, dy, obj)
{
   var _loc6_ = px - obj.pos.x;
   var _loc5_ = py - obj.pos.y;
   var _loc11_ = dx * dx + dy * dy;
   var _loc4_ = 2 * (dx * _loc6_ + dy * _loc5_);
   var _loc12_ = obj.r;
   var _loc14_ = _loc6_ * _loc6_ + _loc5_ * _loc5_ - _loc12_ * _loc12_;
   var _loc9_ = _loc4_ * _loc4_ - 4 * _loc11_ * _loc14_;
   var _loc13_;
   var _loc10_;
   var _loc1_;
   var _loc3_;
   var _loc2_;
   if(0 <= _loc9_)
   {
      _loc13_ = Math.sqrt(_loc9_);
      _loc10_ = 1 / (2 * _loc11_);
      _loc1_ = (- _loc4_ + _loc13_) * _loc10_;
      _loc3_ = (- _loc4_ - _loc13_) * _loc10_;
      if(_loc3_ < 0)
      {
         if(_loc1_ < 0)
         {
            return false;
         }
         _loc2_ = _loc1_;
      }
      else if(_loc1_ < 0)
      {
         _loc2_ = _loc3_;
      }
      else if(_loc3_ < _loc1_)
      {
         _loc2_ = _loc3_;
      }
      else
      {
         _loc2_ = _loc1_;
      }
      out.x = px + _loc2_ * dx;
      out.y = py + _loc2_ * dy;
      return true;
   }
   return false;
}
