function TileMap(rows, cols, xw, yw)
{
   this.xw = xw;
   this.yw = yw;
   this.tw = 2 * this.xw;
   this.th = 2 * this.yw;
   this.rows = rows;
   this.cols = cols;
   this.fullrows = this.rows + 2;
   this.fullcols = this.cols + 2;
   this.minX = this.tw;
   this.minY = this.th;
   this.maxX = this.tw + rows * this.tw;
   this.maxY = this.th + cols * this.th;
   this.grid = new Object();
   this.BUILD_STEPS_REMAINING = 9;
   this.rend = new VectorRenderer();
   this.rend.Clear();
}
TileMap.prototype.Building = function()
{
   var _loc7_ = this.xw;
   var _loc5_ = this.yw;
   var _loc4_ = this.fullrows;
   var _loc2_ = this.fullcols;
   var _loc8_ = this.rows;
   var _loc9_ = this.cols;
   var _loc6_;
   var _loc3_;
   if(this.BUILD_STEPS_REMAINING == 9)
   {
      _loc6_ = 0;
      while(_loc6_ < _loc4_)
      {
         this.grid[_loc6_] = new Object();
         _loc3_ = 0;
         while(_loc3_ < _loc2_)
         {
            this.grid[_loc6_][_loc3_] = new TileMapCell(_loc6_,_loc3_,_loc7_,_loc5_,this.xw,this.yw);
            _loc5_ += this.th;
            _loc3_ = _loc3_ + 1;
         }
         _loc7_ += this.tw;
         _loc5_ = this.yw;
         _loc6_ = _loc6_ + 1;
      }
      this.BUILD_STEPS_REMAINING = this.BUILD_STEPS_REMAINING - 1;
      return true;
   }
   if(this.BUILD_STEPS_REMAINING == 8)
   {
      _loc6_ = 0;
      while(_loc6_ < _loc4_ - 1)
      {
         _loc3_ = 0;
         while(_loc3_ < _loc2_)
         {
            this.grid[_loc6_][_loc3_].LinkR(this.grid[_loc6_ + 1][_loc3_]);
            _loc3_ = _loc3_ + 1;
         }
         _loc6_ = _loc6_ + 1;
      }
      this.BUILD_STEPS_REMAINING = this.BUILD_STEPS_REMAINING - 1;
      return true;
   }
   if(this.BUILD_STEPS_REMAINING == 7)
   {
      _loc6_ = 1;
      while(_loc6_ < _loc4_)
      {
         _loc3_ = 0;
         while(_loc3_ < _loc2_)
         {
            this.grid[_loc6_][_loc3_].LinkL(this.grid[_loc6_ - 1][_loc3_]);
            _loc3_ = _loc3_ + 1;
         }
         _loc6_ = _loc6_ + 1;
      }
      this.BUILD_STEPS_REMAINING = this.BUILD_STEPS_REMAINING - 1;
      return true;
   }
   if(this.BUILD_STEPS_REMAINING == 6)
   {
      _loc6_ = 0;
      while(_loc6_ < _loc4_)
      {
         _loc3_ = 0;
         while(_loc3_ < _loc2_ - 1)
         {
            this.grid[_loc6_][_loc3_].LinkD(this.grid[_loc6_][_loc3_ + 1]);
            _loc3_ = _loc3_ + 1;
         }
         _loc6_ = _loc6_ + 1;
      }
      this.BUILD_STEPS_REMAINING = this.BUILD_STEPS_REMAINING - 1;
      return true;
   }
   if(this.BUILD_STEPS_REMAINING == 5)
   {
      _loc6_ = 0;
      while(_loc6_ < _loc4_)
      {
         _loc3_ = 1;
         while(_loc3_ < _loc2_)
         {
            this.grid[_loc6_][_loc3_].LinkU(this.grid[_loc6_][_loc3_ - 1]);
            _loc3_ = _loc3_ + 1;
         }
         _loc6_ = _loc6_ + 1;
      }
      this.BUILD_STEPS_REMAINING = this.BUILD_STEPS_REMAINING - 1;
      return true;
   }
   if(this.BUILD_STEPS_REMAINING == 4)
   {
      _loc6_ = 0;
      while(_loc6_ < _loc4_)
      {
         this.grid[_loc6_][0].SetState(TID_FULL);
         _loc6_ = _loc6_ + 1;
      }
      this.BUILD_STEPS_REMAINING = this.BUILD_STEPS_REMAINING - 1;
      return true;
   }
   if(this.BUILD_STEPS_REMAINING == 3)
   {
      _loc6_ = 0;
      while(_loc6_ < _loc4_)
      {
         this.grid[_loc6_][_loc2_ - 1].SetState(TID_FULL);
         _loc6_ = _loc6_ + 1;
      }
      this.BUILD_STEPS_REMAINING = this.BUILD_STEPS_REMAINING - 1;
      return true;
   }
   if(this.BUILD_STEPS_REMAINING == 2)
   {
      _loc6_ = 0;
      while(_loc6_ < _loc2_)
      {
         this.grid[0][_loc6_].SetState(TID_FULL);
         _loc6_ = _loc6_ + 1;
      }
      this.BUILD_STEPS_REMAINING = this.BUILD_STEPS_REMAINING - 1;
      return true;
   }
   if(this.BUILD_STEPS_REMAINING == 1)
   {
      _loc6_ = 0;
      while(_loc6_ < _loc2_)
      {
         this.grid[_loc4_ - 1][_loc6_].SetState(TID_FULL);
         _loc6_ = _loc6_ + 1;
      }
      this.BUILD_STEPS_REMAINING = this.BUILD_STEPS_REMAINING - 1;
      return true;
   }
   return false;
};
TileMap.prototype.ClearGrid = function()
{
   var _loc2_;
   for(var _loc4_ in this.grid)
   {
      _loc2_ = this.grid[_loc4_];
      for(_loc3_ in _loc2_)
      {
         _loc2_[_loc3_].next = null;
         _loc2_[_loc3_].prev = null;
      }
   }
};
TileMap.prototype.GetTile_S = function(x, y)
{
   return this.grid[Math.floor(x / this.tw)][Math.floor(y / this.th)];
};
TileMap.prototype.GetTile_V = function(p)
{
   return this.grid[Math.floor(p.x / this.tw)][Math.floor(p.y / this.th)];
};
TileMap.prototype.GetTile_I = function(i, j)
{
   return this.grid[i][j];
};
TileMap.prototype.GetIndex_S = function(v, x, y)
{
   v.x = Math.floor(x / this.tw);
   v.y = Math.floor(y / this.th);
};
TileMap.prototype.GetIndex_V = function(v, p)
{
   v.x = Math.floor(p.x / this.tw);
   v.y = Math.floor(p.y / this.th);
};
