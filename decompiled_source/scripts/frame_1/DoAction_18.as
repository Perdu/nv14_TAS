function QueryPointvsTileMap(x, y)
{
   var _loc1_ = tiles.GetTile_S(x,y);
   return TestPointTile(x,y,_loc1_);
}
