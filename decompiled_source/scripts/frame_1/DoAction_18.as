function evaluate_bwj(x, tile_x)
{
    // we evaluate if found tile is behind or below the player
    // trace(x + ", " + tile_x + ", " + player.facingDir);
    if (
        (x < tile_x && player.facingDir == -1) ||
        (x > tile_x && player.facingDir == 1)
       )
        player.is_bwj = true;
    else
        player.is_bwj = false;
}

function QueryPointvsTileMap(x, y)
{
   var _loc1_ = tiles.GetTile_S(x,y);
   evaluate_bwj(x, _loc1_.pos.x);
   return TestPointTile(x,y,_loc1_);
}
