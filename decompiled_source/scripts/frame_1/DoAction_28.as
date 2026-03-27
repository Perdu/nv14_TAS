function TestPointTile(x, y, t)
{
   if(0 < t.ID)
   {
      return Test_PointTile[t.CTYPE](x,y,t);
   }
   return false;
}
Test_PointTile = new Object();
Test_PointTile[CTYPE_FULL] = TestPoint_Full;
Test_PointTile[CTYPE_45DEG] = TestPoint_45Deg;
Test_PointTile[CTYPE_CONCAVE] = TestPoint_Concave;
Test_PointTile[CTYPE_CONVEX] = TestPoint_Convex;
Test_PointTile[CTYPE_22DEGs] = TestPoint_22DegS;
Test_PointTile[CTYPE_22DEGb] = TestPoint_22DegB;
Test_PointTile[CTYPE_67DEGs] = TestPoint_67DegS;
Test_PointTile[CTYPE_67DEGb] = TestPoint_67DegB;
Test_PointTile[CTYPE_HALF] = TestPoint_Half;
