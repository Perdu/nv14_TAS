function TestPoint_45Deg(x, y, t)
{
   var _loc3_ = x - t.pos.x;
   var _loc2_ = y - t.pos.y;
   if(_loc3_ * t.sx + _loc2_ * t.sy <= 0)
   {
      return true;
   }
   return false;
}
