function ProjAABB_Half(x, y, obj, t)
{
   var _loc3_ = t.signx;
   var _loc2_ = t.signy;
   var _loc10_ = obj.pos.x - _loc3_ * obj.xw - t.pos.x;
   var _loc9_ = obj.pos.y - _loc2_ * obj.yw - t.pos.y;
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
      obj.ReportCollisionVsWorld(_loc3_,_loc2_,t.signx,t.signy,t);
      return COL_OTHER;
   }
   return COL_NONE;
}
