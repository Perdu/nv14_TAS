function TestPoint_Convex(x, y, t)
{
   var _loc4_ = x - (t.pos.x - t.signx * t.xw);
   var _loc3_ = y - (t.pos.y - t.signy * t.yw);
   var _loc2_ = t.xw * 2;
   if(_loc4_ * _loc4_ + _loc3_ * _loc3_ <= _loc2_ * _loc2_)
   {
      return true;
   }
   return false;
}
