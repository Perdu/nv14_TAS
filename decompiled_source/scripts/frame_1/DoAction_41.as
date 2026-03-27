function ProjCircle_Full(x, y, oH, oV, obj, t)
{
   var _loc4_;
   var _loc3_;
   if(oH == 0)
   {
      if(oV == 0)
      {
         if(x < y)
         {
            _loc4_ = obj.pos.x - t.pos.x;
            if(_loc4_ < 0)
            {
               obj.ReportCollisionVsWorld(- x,0,-1,0,t);
               return COL_AXIS;
            }
            obj.ReportCollisionVsWorld(x,0,1,0,t);
            return COL_AXIS;
         }
         _loc3_ = obj.pos.y - t.pos.y;
         if(_loc3_ < 0)
         {
            obj.ReportCollisionVsWorld(0,- y,0,-1,t);
            return COL_AXIS;
         }
         obj.ReportCollisionVsWorld(0,y,0,1,t);
         return COL_AXIS;
      }
      static_rend.DrawCrossR(t.pos,t.xw);
      obj.ReportCollisionVsWorld(0,y * oV,0,oV,t);
      return COL_AXIS;
   }
   if(oV == 0)
   {
      static_rend.DrawCrossR(t.pos,t.xw);
      obj.ReportCollisionVsWorld(x * oH,0,oH,0,t);
      return COL_AXIS;
   }
   static_rend.DrawCrossR(t.pos,t.xw);
   var _loc12_ = t.pos.x + oH * t.xw;
   var _loc11_ = t.pos.y + oV * t.yw;
   _loc4_ = obj.pos.x - _loc12_;
   _loc3_ = obj.pos.y - _loc11_;
   var _loc5_ = Math.sqrt(_loc4_ * _loc4_ + _loc3_ * _loc3_);
   var _loc7_ = obj.r - _loc5_;
   if(0 < _loc7_)
   {
      if(_loc5_ == 0)
      {
         _loc4_ = oH / 1.4142135623730951;
         _loc3_ = oV / 1.4142135623730951;
      }
      else
      {
         _loc4_ /= _loc5_;
         _loc3_ /= _loc5_;
      }
      obj.ReportCollisionVsWorld(_loc4_ * _loc7_,_loc3_ * _loc7_,_loc4_,_loc3_,t);
      return COL_OTHER;
   }
   return COL_NONE;
}
