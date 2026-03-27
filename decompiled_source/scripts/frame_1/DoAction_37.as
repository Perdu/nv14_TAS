function ProjAABB_67DegS(x, y, obj, t)
{
   var _loc8_ = t.signx;
   var _loc13_ = t.signy;
   var _loc14_ = obj.pos.x - _loc8_ * obj.xw;
   var _loc3_ = t.pos.x - _loc14_;
   var _loc16_;
   var _loc15_;
   var _loc5_;
   var _loc4_;
   var _loc9_;
   var _loc10_;
   var _loc7_;
   var _loc6_;
   if(0 < _loc3_ * _loc8_)
   {
      _loc16_ = obj.pos.x - _loc8_ * obj.xw - (t.pos.x - _loc8_ * t.xw);
      _loc15_ = obj.pos.y - _loc13_ * obj.yw - (t.pos.y + _loc13_ * t.yw);
      _loc5_ = t.sx;
      _loc4_ = t.sy;
      _loc9_ = _loc16_ * _loc5_ + _loc15_ * _loc4_;
      if(_loc9_ < 0)
      {
         _loc5_ *= - _loc9_;
         _loc4_ *= - _loc9_;
         _loc10_ = Math.sqrt(_loc5_ * _loc5_ + _loc4_ * _loc4_);
         _loc7_ = Math.sqrt(x * x + y * y);
         _loc6_ = Math.abs(_loc3_);
         if(_loc7_ < _loc10_)
         {
            if(_loc6_ < _loc7_)
            {
               obj.ReportCollisionVsWorld(_loc3_,0,_loc3_ / _loc6_,0,t);
               return COL_OTHER;
            }
            obj.ReportCollisionVsWorld(x,y,x / _loc7_,y / _loc7_,t);
            return COL_AXIS;
         }
         if(_loc6_ < _loc10_)
         {
            obj.ReportCollisionVsWorld(_loc3_,0,_loc3_ / _loc6_,0,t);
            return COL_OTHER;
         }
         obj.ReportCollisionVsWorld(_loc5_,_loc4_,t.sx,t.sy,t);
         return COL_OTHER;
      }
   }
   return COL_NONE;
}
