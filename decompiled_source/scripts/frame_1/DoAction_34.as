function ProjAABB_45Deg(x, y, obj, t)
{
   var _loc13_ = t.signx;
   var _loc12_ = t.signy;
   var _loc10_ = obj.pos.x - _loc13_ * obj.xw - t.pos.x;
   var _loc9_ = obj.pos.y - _loc12_ * obj.yw - t.pos.y;
   var _loc3_ = t.sx;
   var _loc2_ = t.sy;
   var _loc6_ = _loc10_ * _loc3_ + _loc9_ * _loc2_;
   var _loc11_;
   var _loc5_;
   if(_loc6_ < 0)
   {
      _loc3_ *= - _loc6_;
      _loc2_ *= - _loc6_;
      _loc11_ = Math.sqrt(_loc3_ * _loc3_ + _loc2_ * _loc2_);
      _loc5_ = Math.sqrt(x * x + y * y);
      if(_loc5_ < _loc11_)
      {
         obj.ReportCollisionVsWorld(x,y,x / _loc5_,y / _loc5_,t);
         return COL_AXIS;
      }
      obj.ReportCollisionVsWorld(_loc3_,_loc2_,t.sx,t.sy);
      return COL_OTHER;
   }
   return COL_NONE;
}
