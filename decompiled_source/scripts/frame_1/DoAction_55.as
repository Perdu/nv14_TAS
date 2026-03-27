function TestRay_AABB(out, px, py, dx, dy, obj)
{
   var _loc4_ = obj.pos.x;
   var _loc2_ = obj.pos.y;
   var _loc6_ = obj.xw;
   var _loc7_ = obj.yw;
   var _loc9_;
   var _loc8_;
   if(px < _loc4_)
   {
      _loc9_ = _loc4_ - _loc6_;
   }
   else
   {
      _loc9_ = _loc4_ + _loc6_;
   }
   if(py < _loc2_)
   {
      _loc8_ = _loc2_ - _loc7_;
   }
   else
   {
      _loc8_ = _loc2_ + _loc7_;
   }
   var _loc1_;
   var _loc13_;
   var _loc11_;
   var _loc12_;
   var _loc10_;
   var _loc19_;
   var _loc18_;
   if(dx == 0)
   {
      if(dy == 0)
      {
         return false;
      }
      _loc13_ = _loc4_ - _loc6_;
      _loc12_ = _loc4_ + _loc6_;
      _loc11_ = _loc10_ = _loc8_;
      _loc1_ = (_loc8_ - py) / dy;
   }
   else if(dy == 0)
   {
      _loc11_ = _loc2_ - _loc7_;
      _loc10_ = _loc2_ + _loc7_;
      _loc13_ = _loc12_ = _loc9_;
      _loc1_ = (_loc9_ - px) / dx;
   }
   else
   {
      _loc19_ = (_loc9_ - px) / dx;
      _loc18_ = (_loc8_ - py) / dy;
      if(_loc19_ < _loc18_)
      {
         _loc13_ = _loc4_ - _loc6_;
         _loc12_ = _loc4_ + _loc6_;
         _loc11_ = _loc10_ = _loc8_;
         _loc1_ = _loc18_;
      }
      else
      {
         _loc11_ = _loc2_ - _loc7_;
         _loc10_ = _loc2_ + _loc7_;
         _loc13_ = _loc12_ = _loc9_;
         _loc1_ = _loc19_;
      }
   }
   var _loc22_;
   var _loc20_;
   var _loc17_;
   var _loc16_;
   if(0 < _loc1_)
   {
      _loc22_ = px + 100 * dx;
      _loc20_ = py + 100 * dy;
      _loc17_ = (_loc22_ - px) * (_loc11_ - py) - (_loc13_ - px) * (_loc20_ - py);
      _loc16_ = (_loc22_ - px) * (_loc10_ - py) - (_loc12_ - px) * (_loc20_ - py);
      if(_loc17_ * _loc16_ < 0)
      {
         out.x = px + _loc1_ * dx;
         out.y = py + _loc1_ * dy;
         return true;
      }
      return false;
   }
   return false;
}
