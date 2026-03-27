function ProjAABB_Full(x, y, obj, t)
{
   var _loc1_ = Math.sqrt(x * x + y * y);
   obj.ReportCollisionVsWorld(x,y,x / _loc1_,y / _loc1_,t);
   return COL_AXIS;
}
