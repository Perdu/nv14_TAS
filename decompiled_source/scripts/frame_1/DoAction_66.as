function TestRayObj(out, px, py, dx, dy, obj)
{
   if(obj.OTYPE == OTYPE_AABB)
   {
      return TestRay_AABB(out,px,py,dx,dy,obj);
   }
   return TestRay_Circle(out,px,py,dx,dy,obj);
}
