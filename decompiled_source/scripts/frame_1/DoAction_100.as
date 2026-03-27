NinjaEditor.prototype.StartEditTiles = function()
{
   gui.Display(GUI_TILE_EDITOR);
   gui.HideTxt();
   this.tileCurType = 1;
   this.pointer.txt = "";
   this.pointer._visible = false;
   this.objMenuMC._visible = false;
   this.tileMenuMC._visible = true;
   this.tileMenuMC.gotoAndStop(1);
   this.pointer.objhelp._visible = false;
   this.RefreshTileMenu();
   this.Tick = this.TickEditTiles;
   this.StopEdit = this.StopEditTiles;
   this.StartTileMode_Paint();
   this.selrend.Clear();
   this.selrend.Show();
};
NinjaEditor.prototype.StopEditTiles = function()
{
   this.pointer._visible = false;
   this.objMenuMC._visible = false;
   this.tileMenuMC._visible = false;
   this.selrend.Hide();
};
NinjaEditor.prototype.RefreshTileMenu = function()
{
   var _loc2_ = input.getMousePos();
   if(_loc2_.y < 300)
   {
      this.tileMenuMC._y = 450;
   }
   else
   {
      this.tileMenuMC._y = 150;
   }
};
NinjaEditor.prototype.TickEditTiles = function()
{
   this.TickGrid();
   if(Key.isDown(36))
   {
      this.StartEditMenu();
      return undefined;
   }
   if(Key.isDown(45) || Key.isDown(96))
   {
      this.StopEdit();
      this.StartEditObjects();
   }
   this.TickCurrentTileMode();
};
NinjaEditor.prototype.StartTileMode_Paint = function()
{
   this.TickCurrentTileMode = this.TickCurrentTileMode_Paint;
   this.tilemin.x = this.tilemin.y = this.tilemax.x = this.tilemax.y = -1;
   this.selrend.Clear();
   this.tileMenuMC._visible = true;
   this.RefreshTileMenu();
};
NinjaEditor.prototype.TickCurrentTileMode_Paint = function()
{
   if(input.MousePressed())
   {
      this.StartTileMode_ClipBoard();
      return undefined;
   }
   var _loc3_ = input.getMousePos();
   var _loc5_ = APP_TILE_SCALE * 2;
   _loc3_.x = Math.min(792 - (_loc5_ + 1),Math.max(_loc5_,_loc3_.x));
   _loc3_.y = Math.min(600 - (_loc5_ + 1),Math.max(_loc5_,_loc3_.y));
   var _loc2_ = tiles.GetTile_V(_loc3_);
   this.rend.Clear();
   this.rend.SetStyle(0,0,30);
   this.rend.DrawAABB(_loc2_.pos,_loc2_.xw,_loc2_.yw);
   var _loc6_ = new Vector2(_loc3_.x,_loc3_.y);
   this.pointer._x = _loc6_.x;
   this.pointer._y = _loc6_.y;
   this.RefreshTileMenu();
   if(Key.isDown(49))
   {
      this.tileCurType = 1;
   }
   else if(Key.isDown(50))
   {
      this.tileCurType = 2;
   }
   else if(Key.isDown(51))
   {
      this.tileCurType = 3;
   }
   else if(Key.isDown(52))
   {
      this.tileCurType = 4;
   }
   else if(Key.isDown(53))
   {
      this.tileCurType = 5;
   }
   else if(Key.isDown(54))
   {
      this.tileCurType = 6;
   }
   else if(Key.isDown(55))
   {
      this.tileCurType = 7;
   }
   else if(Key.isDown(56))
   {
      this.tileCurType = 8;
   }
   var _loc4_;
   if(Key.isDown(16))
   {
      if(this.tileCurType <= 4)
      {
         _loc4_ = this.tileCurType + 4;
      }
      else
      {
         _loc4_ = this.tileCurType - 4;
      }
   }
   else
   {
      _loc4_ = this.tileCurType;
   }
   this.tileMenuMC.gotoAndStop(_loc4_);
   if(Key.isDown(68))
   {
      _loc2_.Clear();
   }
   else if(Key.isDown(69))
   {
      _loc2_.SetState(TID_FULL);
   }
   else if(Key.isDown(81))
   {
      _loc2_.SetState(this.tileTypeList[_loc4_][0]);
   }
   else if(Key.isDown(65))
   {
      _loc2_.SetState(this.tileTypeList[_loc4_][1]);
   }
   else if(Key.isDown(83))
   {
      _loc2_.SetState(this.tileTypeList[_loc4_][2]);
   }
   else if(Key.isDown(87))
   {
      _loc2_.SetState(this.tileTypeList[_loc4_][3]);
   }
};
NinjaEditor.prototype.StartTileMode_ClipBoard = function()
{
   this.TickCurrentTileMode = this.TickCurrentTileMode_ClipBoard;
   this.tilemode = 0;
   var _loc2_ = input.getMousePos();
   var _loc3_ = APP_TILE_SCALE * 2;
   _loc2_.x = Math.min(792 - (_loc3_ + 1),Math.max(_loc3_,_loc2_.x));
   _loc2_.y = Math.min(600 - (_loc3_ + 1),Math.max(_loc3_,_loc2_.y));
   var _loc4_ = tiles.GetTile_V(_loc2_);
   this.tilesel_start = _loc4_;
   this.tilesel_end = null;
   this.tilemin.x = this.tilemin.y = this.tilemax.x = this.tilemax.y = -1;
   this.tilesel_iw = 0;
   this.tilesel_jw = 0;
   this.selrend.Clear();
   this.RefreshTileMenu();
   this.tileMenuMC.gotoAndStop(9);
};
NinjaEditor.prototype.TickCurrentTileMode_ClipBoard = function()
{
   this.RefreshTileMenu();
   var _loc8_ = input.getMousePos();
   var _loc9_ = APP_TILE_SCALE * 2;
   _loc8_.x = Math.min(792 - (_loc9_ + 1),Math.max(_loc9_,_loc8_.x));
   _loc8_.y = Math.min(600 - (_loc9_ + 1),Math.max(_loc9_,_loc8_.y));
   var _loc7_ = tiles.GetTile_V(_loc8_);
   this.rend.Clear();
   this.rend.SetStyle(0,0,30);
   this.rend.DrawAABB(_loc7_.pos,_loc7_.xw,_loc7_.yw);
   var _loc10_ = new Vector2(_loc8_.x,_loc8_.y);
   this.pointer._x = _loc10_.x;
   this.pointer._y = _loc10_.y;
   var _loc14_;
   var _loc13_;
   var _loc15_;
   var _loc17_;
   var _loc16_;
   var _loc6_;
   var _loc2_;
   var _loc5_;
   var _loc12_;
   var _loc11_;
   var _loc4_;
   var _loc3_;
   if(input.MousePressed())
   {
      this.StartTileMode_ClipBoard();
   }
   else if(input.MouseDown())
   {
      _loc14_ = this.tilesel_start.pos.x - _loc7_.pos.x;
      _loc13_ = this.tilesel_start.pos.y - _loc7_.pos.y;
      _loc15_ = Math.abs(_loc14_);
      _loc17_ = Math.abs(_loc13_);
      this.selrend.Clear();
      this.selrend.SetStyle(3,16777215,30);
      _loc16_ = new Vector2(_loc7_.pos.x + 0.5 * _loc14_,_loc7_.pos.y + 0.5 * _loc13_);
      this.selrend.DrawAABB(_loc16_,0.5 * _loc15_ + _loc7_.xw,0.5 * _loc17_ + _loc7_.yw);
   }
   else if(input.MouseReleased())
   {
      this.tilesel_end = _loc7_;
      if(this.tilesel_start == this.tilesel_end)
      {
         this.StartTileMode_Paint();
         return undefined;
      }
      this.tilemode = 1;
      this.tilemin.x = Math.min(this.tilesel_start.i,this.tilesel_end.i);
      this.tilemin.y = Math.min(this.tilesel_start.j,this.tilesel_end.j);
      this.tilemax.x = Math.max(this.tilesel_start.i,this.tilesel_end.i);
      this.tilemax.y = Math.max(this.tilesel_start.j,this.tilesel_end.j);
      this.tilesel_iw = this.tilemax.x - this.tilemin.x;
      this.tilesel_jw = this.tilemax.y - this.tilemin.y;
      this.tilestateList = new Array();
      _loc6_ = 0;
      while(_loc6_ < this.tilesel_iw + 1)
      {
         this.tilestateList[_loc6_] = new Array();
         _loc2_ = 0;
         while(_loc2_ < this.tilesel_jw + 1)
         {
            _loc5_ = tiles.GetTile_I(this.tilemin.x + _loc6_,this.tilemin.y + _loc2_);
            this.tilestateList[_loc6_][_loc2_] = _loc5_.ID;
            _loc2_ = _loc2_ + 1;
         }
         _loc6_ = _loc6_ + 1;
      }
   }
   else
   {
      _loc14_ = this.tilesel_start.pos.x - this.tilesel_end.pos.x;
      _loc13_ = this.tilesel_start.pos.y - this.tilesel_end.pos.y;
      _loc15_ = Math.abs(_loc14_);
      _loc17_ = Math.abs(_loc13_);
      this.selrend.Clear();
      this.selrend.SetStyle(3,16777215,30);
      _loc16_ = new Vector2(this.tilesel_end.pos.x + 0.5 * _loc14_,this.tilesel_end.pos.y + 0.5 * _loc13_);
      this.selrend.DrawAABB(_loc16_,0.5 * _loc15_ + this.tilesel_end.xw,0.5 * _loc17_ + this.tilesel_end.yw);
      _loc12_ = Math.min(APP_NUM_GRIDCOLS,Math.max(1,_loc7_.i + this.tilesel_iw));
      _loc11_ = Math.min(APP_NUM_GRIDROWS,Math.max(1,_loc7_.j + this.tilesel_jw));
      _loc4_ = _loc12_ - this.tilesel_iw;
      _loc3_ = _loc11_ - this.tilesel_jw;
      _loc14_ = this.tilesel_iw * 2 * APP_TILE_SCALE;
      _loc13_ = this.tilesel_jw * 2 * APP_TILE_SCALE;
      _loc15_ = Math.abs(_loc14_);
      _loc17_ = Math.abs(_loc13_);
      this.selrend.SetStyle(3,10066329,30);
      _loc16_ = new Vector2(APP_TILE_SCALE + _loc4_ * 2 * APP_TILE_SCALE + 0.5 * _loc14_,APP_TILE_SCALE + _loc3_ * 2 * APP_TILE_SCALE + 0.5 * _loc13_);
      this.selrend.DrawAABB(_loc16_,0.5 * _loc15_ + APP_TILE_SCALE,0.5 * _loc17_ + APP_TILE_SCALE);
      if(Key.isDown(67))
      {
         if(this.tilemode == 1)
         {
            this.tilemode = 0;
            _loc6_ = 0;
            while(_loc6_ < this.tilesel_iw + 1)
            {
               _loc2_ = 0;
               while(_loc2_ < this.tilesel_jw + 1)
               {
                  _loc5_ = tiles.GetTile_I(_loc4_ + _loc6_,_loc3_ + _loc2_);
                  _loc5_.SetState(this.tilestateList[_loc6_][_loc2_]);
                  _loc2_ = _loc2_ + 1;
               }
               _loc6_ = _loc6_ + 1;
            }
         }
      }
      else if(Key.isDown(88))
      {
         if(this.tilemode == 1)
         {
            this.tilemode = 0;
            _loc6_ = 0;
            while(_loc6_ < this.tilesel_iw + 1)
            {
               _loc2_ = 0;
               while(_loc2_ < this.tilesel_jw + 1)
               {
                  _loc5_ = tiles.GetTile_I(this.tilemin.x + _loc6_,this.tilemin.y + _loc2_);
                  _loc5_.Clear();
                  _loc2_ = _loc2_ + 1;
               }
               _loc6_ = _loc6_ + 1;
            }
            _loc6_ = 0;
            while(_loc6_ < this.tilesel_iw + 1)
            {
               _loc2_ = 0;
               while(_loc2_ < this.tilesel_jw + 1)
               {
                  _loc5_ = tiles.GetTile_I(_loc4_ + _loc6_,_loc3_ + _loc2_);
                  _loc5_.SetState(this.tilestateList[_loc6_][_loc2_]);
                  _loc2_ = _loc2_ + 1;
               }
               _loc6_ = _loc6_ + 1;
            }
            this.tilesel_start = tiles.GetTile_I(_loc4_,_loc3_);
            this.tilesel_end = tiles.GetTile_I(_loc12_,_loc11_);
            this.tilemin.x = Math.min(this.tilesel_start.i,this.tilesel_end.i);
            this.tilemin.y = Math.min(this.tilesel_start.j,this.tilesel_end.j);
            this.tilemax.x = Math.max(this.tilesel_start.i,this.tilesel_end.i);
            this.tilemax.y = Math.max(this.tilesel_start.j,this.tilesel_end.j);
         }
      }
      else if(Key.isDown(90))
      {
         if(this.tilemode == 1)
         {
            this.tilemode = 0;
            _loc6_ = 0;
            while(_loc6_ < this.tilesel_iw + 1)
            {
               _loc2_ = 0;
               while(_loc2_ < this.tilesel_jw + 1)
               {
                  _loc5_ = tiles.GetTile_I(_loc4_ + _loc6_,_loc3_ + _loc2_);
                  _loc5_.Clear();
                  _loc2_ = _loc2_ + 1;
               }
               _loc6_ = _loc6_ + 1;
            }
         }
      }
      else if(Key.isDown(65))
      {
         if(this.tilemode == 1)
         {
            this.tilemode = 0;
            _loc6_ = 0;
            while(_loc6_ < this.tilesel_iw + 1)
            {
               _loc2_ = 0;
               while(_loc2_ < this.tilesel_jw + 1)
               {
                  _loc5_ = tiles.GetTile_I(_loc4_ + _loc6_,_loc3_ + _loc2_);
                  _loc5_.SetState(TID_FULL);
                  _loc2_ = _loc2_ + 1;
               }
               _loc6_ = _loc6_ + 1;
            }
         }
      }
      else
      {
         this.tilemode = 1;
      }
   }
};
