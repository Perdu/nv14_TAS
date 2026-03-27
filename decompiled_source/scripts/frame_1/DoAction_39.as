function ResolveBoxTile(x, y, box, t)
{
   if(0 < t.ID)
   {
      return Proj_AABBTile[t.CTYPE](x,y,box,t);
   }
   return false;
}
Proj_AABBTile = new Object();
Proj_AABBTile[CTYPE_FULL] = ProjAABB_Full;
Proj_AABBTile[CTYPE_45DEG] = ProjAABB_45Deg;
Proj_AABBTile[CTYPE_CONCAVE] = ProjAABB_Concave;
Proj_AABBTile[CTYPE_CONVEX] = ProjAABB_Convex;
Proj_AABBTile[CTYPE_22DEGs] = ProjAABB_22DegS;
Proj_AABBTile[CTYPE_22DEGb] = ProjAABB_22DegB;
Proj_AABBTile[CTYPE_67DEGs] = ProjAABB_67DegS;
Proj_AABBTile[CTYPE_67DEGb] = ProjAABB_67DegB;
Proj_AABBTile[CTYPE_HALF] = ProjAABB_Half;
