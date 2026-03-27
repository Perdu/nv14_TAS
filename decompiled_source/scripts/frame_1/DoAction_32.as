function ProjAABB_Concave(x, y, obj, t)
{
   var _loc12_ = t.signx;
   var _loc11_ = t.signy;
   var _loc3_ = t.pos.x + _loc12_ * t.xw - (obj.pos.x - _loc12_ * obj.xw);
   var _loc2_ = t.pos.y + _loc11_ * t.yw - (obj.pos.y - _loc11_ * obj.yw);
   var _loc8_ = t.xw * 2;
   var _loc13_ = Math.sqrt(_loc8_ * _loc8_ + 0);
   var _loc6_ = Math.sqrt(_loc3_ * _loc3_ + _loc2_ * _loc2_);
   var _loc4_ = _loc6_ - _loc13_;
   var _loc7_;
   if(0 < _loc4_)
   {
      _loc7_ = Math.sqrt(x * x + y * y);
      if(_loc7_ < _loc4_)
      {
         obj.ReportCollisionVsWorld(x,y,x / _loc7_,y / _loc7_,t);
         return COL_AXIS;
      }
      _loc3_ /= _loc6_;
      _loc2_ /= _loc6_;
      obj.ReportCollisionVsWorld(_loc3_ * _loc4_,_loc2_ * _loc4_,_loc3_,_loc2_,t);
      return COL_OTHER;
   }
   return COL_NONE;
}
