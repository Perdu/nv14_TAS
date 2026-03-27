function ResolveCircleTile(x, y, oH, oV, obj, t)
{
   if(debug)
   {
      _root.resolveCircleText.text = Math.round(Number(x) * 1000) / 1000 + ", " + Math.round(Number(y) * 1000) / 1000;
   }
   if(0 < t.ID)
   {
      return Proj_CircleTile[t.CTYPE](x,y,oH,oV,obj,t);
   }
   return false;
}
Proj_CircleTile = new Object();
Proj_CircleTile[CTYPE_FULL] = ProjCircle_Full;
Proj_CircleTile[CTYPE_45DEG] = ProjCircle_45Deg;
Proj_CircleTile[CTYPE_CONCAVE] = ProjCircle_Concave;
Proj_CircleTile[CTYPE_CONVEX] = ProjCircle_Convex;
Proj_CircleTile[CTYPE_22DEGs] = ProjCircle_22DegS;
Proj_CircleTile[CTYPE_22DEGb] = ProjCircle_22DegB;
Proj_CircleTile[CTYPE_67DEGs] = ProjCircle_67DegS;
Proj_CircleTile[CTYPE_67DEGb] = ProjCircle_67DegB;
Proj_CircleTile[CTYPE_HALF] = ProjCircle_Half;
