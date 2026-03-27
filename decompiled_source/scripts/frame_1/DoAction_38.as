function ProjAABB_67DegB(x, y, obj, t)
{
   var _loc10_ = t.signx;
   var _loc9_ = t.signy;
   var _loc12_ = obj.pos.x - _loc10_ * obj.xw - (t.pos.x + _loc10_ * t.xw);
   var _loc11_ = obj.pos.y - _loc9_ * obj.yw - (t.pos.y - _loc9_ * t.yw);
   var _loc3_ = t.sx;
   var _loc2_ = t.sy;
   var _loc6_ = _loc12_ * _loc3_ + _loc11_ * _loc2_;
   var _loc13_;
   var _loc5_;
   if(_loc6_ < 0)
   {
      _loc3_ *= - _loc6_;
      _loc2_ *= - _loc6_;
      _loc13_ = Math.sqrt(_loc3_ * _loc3_ + _loc2_ * _loc2_);
      _loc5_ = Math.sqrt(x * x + y * y);
      if(_loc5_ < _loc13_)
      {
         obj.ReportCollisionVsWorld(x,y,x / _loc5_,y / _loc5_,t);
         return COL_AXIS;
      }
      obj.ReportCollisionVsWorld(_loc3_,_loc2_,t.sx,t.sy,t);
      return COL_OTHER;
   }
   return COL_NONE;
}
