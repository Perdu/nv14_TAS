function TestPoint_Half(x, y, t)
{
   var _loc3_ = t.signx;
   var _loc2_ = t.signy;
   var _loc5_ = x - t.pos.x;
   var _loc4_ = y - t.pos.y;
   if(_loc5_ * _loc3_ + _loc4_ * _loc2_ <= 0)
   {
      return true;
   }
   return false;
}
