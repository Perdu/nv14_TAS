function TestRayTile(out, px, py, dx, dy, t)
{
   if(0 < t.ID)
   {
      return TestRay_Tile[t.CTYPE](out,px,py,dx,dy,t);
   }
   return false;
}
TestRay_Tile = new Object();
TestRay_Tile[CTYPE_FULL] = TestRay_Full;
TestRay_Tile[CTYPE_45DEG] = TestRay_45Deg;
TestRay_Tile[CTYPE_CONCAVE] = TestRay_Concave;
TestRay_Tile[CTYPE_CONVEX] = TestRay_Convex;
TestRay_Tile[CTYPE_22DEGs] = TestRay_22DegS;
TestRay_Tile[CTYPE_22DEGb] = TestRay_22DegB;
TestRay_Tile[CTYPE_67DEGs] = TestRay_67DegS;
TestRay_Tile[CTYPE_67DEGb] = TestRay_67DegB;
TestRay_Tile[CTYPE_HALF] = TestRay_Half;
