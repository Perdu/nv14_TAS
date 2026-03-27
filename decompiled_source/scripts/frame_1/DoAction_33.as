function ProjAABB_Convex(x, y, obj, t)
{
   var _loc8_ = t.signx;
   var _loc7_ = t.signy;
   var _loc3_ = obj.pos.x - _loc8_ * obj.xw - (t.pos.x - _loc8_ * t.xw);
   var _loc2_ = obj.pos.y - _loc7_ * obj.yw - (t.pos.y - _loc7_ * t.yw);
   var _loc5_ = Math.sqrt(_loc3_ * _loc3_ + _loc2_ * _loc2_);
   var _loc9_ = t.xw * 2;
   var _loc13_ = Math.sqrt(_loc9_ * _loc9_ + 0);
   var _loc6_ = _loc13_ - _loc5_;
   var _loc10_;
   if(_loc8_ * _loc3_ < 0 || _loc7_ * _loc2_ < 0)
   {
      _loc10_ = Math.sqrt(x * x + y * y);
      obj.ReportCollisionVsWorld(x,y,x / _loc10_,y / _loc10_,t);
      return COL_AXIS;
   }
   if(0 < _loc6_)
   {
      _loc3_ /= _loc5_;
      _loc2_ /= _loc5_;
      obj.ReportCollisionVsWorld(_loc3_ * _loc6_,_loc2_ * _loc6_,_loc3_,_loc2_,t);
      return COL_OTHER;
   }
   return COL_NONE;
}
