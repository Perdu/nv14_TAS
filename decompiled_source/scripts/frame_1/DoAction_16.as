CHAR_PAD = 48;
TileMap.prototype.GetTileStates = function()
{
   var _loc8_ = this.rows;
   var _loc6_ = this.cols;
   var _loc7_ = this.grid;
   var _loc5_ = "";
   var _loc4_;
   var _loc3_ = 0;
   var _loc2_;
   while(_loc3_ < _loc8_)
   {
      _loc4_ = _loc7_[_loc3_ + 1];
      _loc2_ = 0;
      while(_loc2_ < _loc6_)
      {
         _loc5_ += String.fromCharCode(_loc4_[_loc2_ + 1].ID + CHAR_PAD);
         _loc2_ = _loc2_ + 1;
      }
      _loc3_ = _loc3_ + 1;
   }
   return _loc5_;
};
TileMap.prototype.SetTileState = function(i, j, char)
{
   this.grid[i + 1][j + 1].SetState(char - CHAR_PAD);
};
TileMap.prototype.SetTileStates = function(instr)
{
   var _loc8_ = this.rows;
   var _loc6_ = this.cols;
   var _loc10_ = this.grid;
   var _loc5_ = new Array();
   var _loc7_;
   var _loc3_ = 0;
   var _loc2_;
   var _loc4_;
   while(_loc3_ < _loc8_)
   {
      _loc5_[_loc3_] = new Array();
      _loc2_ = 0;
      while(_loc2_ < _loc6_)
      {
         _loc4_ = instr.charCodeAt(cnum);
         _loc5_[_loc3_][_loc2_] = _loc4_;
         cnum++;
         _loc2_ = _loc2_ + 1;
      }
      _loc3_ = _loc3_ + 1;
   }
   _loc3_ = 0;
   while(_loc3_ < _loc8_)
   {
      _loc7_ = _loc10_[_loc3_ + 1];
      _loc2_ = 0;
      while(_loc2_ < _loc6_)
      {
         _loc7_[_loc2_ + 1].SetState(_loc5_[_loc3_][_loc2_] - CHAR_PAD);
         _loc2_ = _loc2_ + 1;
      }
      _loc3_ = _loc3_ + 1;
   }
};
