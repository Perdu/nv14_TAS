function TestPoint_67DegB(x, y, t)
{
   var _loc3_ = x - (t.pos.x + t.signx * t.xw);
   var _loc2_ = y - (t.pos.y - t.signy * t.yw);
   if(_loc3_ * t.sx + _loc2_ * t.sy <= 0)
   {
      return true;
   }
   return false;
}
