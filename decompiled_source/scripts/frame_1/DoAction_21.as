function TestPoint_Concave(x, y, t)
{
   var _loc4_ = t.pos.x + t.signx * t.xw - x;
   var _loc3_ = t.pos.y + t.signy * t.yw - y;
   var _loc2_ = t.xw * 2;
   if(_loc2_ * _loc2_ <= _loc4_ * _loc4_ + _loc3_ * _loc3_)
   {
      return true;
   }
   return false;
}
