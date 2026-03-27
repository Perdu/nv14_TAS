function NinjaEditor()
{
}
EOBJTYPE_GOLD = 0;
EOBJTYPE_BOUNCEBLOCK = 1;
EOBJTYPE_LAUNCHPAD = 2;
EOBJTYPE_TURRET = 3;
EOBJTYPE_FLOORGUARD = 4;
EOBJTYPE_PLAYER = 5;
EOBJTYPE_MINE = 6;
EOBJTYPE_ONEWAYPLATFORM = 7;
EOBJTYPE_THWOMP = 8;
EOBJTYPE_EXIT = 9;
EOBJTYPE_HOMINGLAUNCHER = 10;
EOBJTYPE_TREKDOOR = 11;
EOBJTYPE_LOCKDOOR = 12;
EOBJTYPE_TRAPDOOR = 13;
EOBJTYPE_ZAPDRONE = 14;
EOBJTYPE_LASERDRONE = 15;
EOBJTYPE_CHAINGUNDRONE = 16;
NinjaEditor.prototype.Init = function()
{
   this.levStr = "";
   this.mapStr = "";
   this.objStr = "";
   this.gridrend = new VectorRenderer();
   var _loc2_ = gfx.CreateEmptySprite(LAYER_EDITOR);
   gfx.DestroyMC(this.gridrend.buffer);
   this.gridrend.buffer = _loc2_;
   this.gridAlpha = 40;
   this.gridmode = 0;
   this.doorrendList = new Array();
   this.doortrigsvis = true;
   this.selrend = new VectorRenderer();
   this.tilemode = 0;
   this.tilemin = new Vector2(0,0);
   this.tilemax = new Vector2(0,0);
   this.tilesel_start = null;
   this.tilesel_end = null;
   this.rend = new VectorRenderer();
   this.objList = new Array();
   this.objnum = 0;
   this.pointer = gfx.CreateSprite("editorCursor",LAYER_EDITORGUI);
   this.pointer._visible = false;
   this.objMenuMC = gfx.CreateSprite("editorObjMenuMC",LAYER_EDITORGUI);
   this.objMenuMC._x = 0;
   this.objMenuMC._y = 0;
   this.objMenuMC._visible = false;
   this.tileMenuMC = gfx.CreateSprite("editorTileMenuMC",LAYER_EDITORGUI);
   this.tileMenuMC._x = 100;
   this.tileMenuMC._y = 0;
   this.tileMenuMC._visible = false;
   this.setObjTypeKeys = new Object();
   this.setObjTypeKeys[EOBJTYPE_GOLD] = 48;
   this.setObjTypeKeys[EOBJTYPE_BOUNCEBLOCK] = 189;
   this.setObjTypeKeys[EOBJTYPE_LAUNCHPAD] = 187;
   this.setObjTypeKeys[EOBJTYPE_TURRET] = 49;
   this.setObjTypeKeys[EOBJTYPE_FLOORGUARD] = 52;
   this.setObjTypeKeys[EOBJTYPE_PLAYER] = 57;
   this.setObjTypeKeys[EOBJTYPE_MINE] = 51;
   this.setObjTypeKeys[EOBJTYPE_ONEWAYPLATFORM] = 219;
   this.setObjTypeKeys[EOBJTYPE_THWOMP] = 53;
   this.setObjTypeKeys[EOBJTYPE_EXIT] = 221;
   this.setObjTypeKeys[EOBJTYPE_HOMINGLAUNCHER] = 50;
   this.setObjTypeKeys[EOBJTYPE_TREKDOOR] = 73;
   this.setObjTypeKeys[EOBJTYPE_LOCKDOOR] = 79;
   this.setObjTypeKeys[EOBJTYPE_TRAPDOOR] = 80;
   this.setObjTypeKeys[EOBJTYPE_ZAPDRONE] = 54;
   this.setObjTypeKeys[EOBJTYPE_LASERDRONE] = 55;
   this.setObjTypeKeys[EOBJTYPE_CHAINGUNDRONE] = 56;
   this.currentEOBJTYPE = EOBJTYPE_GOLD;
   this.currentOBJTYPE = OBJTYPE_GOLD;
   this.objTypes = new Object();
   this.objTypes[EOBJTYPE_GOLD] = OBJTYPE_GOLD;
   this.objTypes[EOBJTYPE_BOUNCEBLOCK] = OBJTYPE_BOUNCEBLOCK;
   this.objTypes[EOBJTYPE_LAUNCHPAD] = OBJTYPE_LAUNCHPAD;
   this.objTypes[EOBJTYPE_TURRET] = OBJTYPE_TURRET;
   this.objTypes[EOBJTYPE_FLOORGUARD] = OBJTYPE_FLOORGUARD;
   this.objTypes[EOBJTYPE_PLAYER] = OBJTYPE_PLAYER;
   this.objTypes[EOBJTYPE_MINE] = OBJTYPE_MINE;
   this.objTypes[EOBJTYPE_ONEWAYPLATFORM] = OBJTYPE_ONEWAYPLATFORM;
   this.objTypes[EOBJTYPE_THWOMP] = OBJTYPE_THWOMP;
   this.objTypes[EOBJTYPE_EXIT] = OBJTYPE_EXIT;
   this.objTypes[EOBJTYPE_HOMINGLAUNCHER] = OBJTYPE_HOMINGLAUNCHER;
   this.objTypes[EOBJTYPE_TREKDOOR] = OBJTYPE_TESTDOOR;
   this.objTypes[EOBJTYPE_LOCKDOOR] = OBJTYPE_TESTDOOR;
   this.objTypes[EOBJTYPE_TRAPDOOR] = OBJTYPE_TESTDOOR;
   this.objTypes[EOBJTYPE_ZAPDRONE] = OBJTYPE_DRONE;
   this.objTypes[EOBJTYPE_LASERDRONE] = OBJTYPE_DRONE;
   this.objTypes[EOBJTYPE_CHAINGUNDRONE] = OBJTYPE_DRONE;
   this.tileTypeList = new Object();
   this.tileTypeList[1] = new Array(TID_45DEGnn,TID_45DEGnp,TID_45DEGpp,TID_45DEGpn);
   this.tileTypeList[2] = new Array(TID_67DEGnnS,TID_67DEGnpS,TID_67DEGppS,TID_67DEGpnS);
   this.tileTypeList[3] = new Array(TID_22DEGnnS,TID_22DEGnpS,TID_22DEGppS,TID_22DEGpnS);
   this.tileTypeList[4] = new Array(TID_CONCAVEnn,TID_CONCAVEnp,TID_CONCAVEpp,TID_CONCAVEpn);
   this.tileTypeList[5] = new Array(TID_HALFl,TID_HALFd,TID_HALFr,TID_HALFu);
   this.tileTypeList[6] = new Array(TID_67DEGnnB,TID_67DEGnpB,TID_67DEGppB,TID_67DEGpnB);
   this.tileTypeList[7] = new Array(TID_22DEGnnB,TID_22DEGnpB,TID_22DEGppB,TID_22DEGpnB);
   this.tileTypeList[8] = new Array(TID_CONVEXnn,TID_CONVEXnp,TID_CONVEXpp,TID_CONVEXpn);
   this.tileCurType = 1;
   this.MUST_BUILD_EDIT_OBJS = false;
};
NinjaEditor.prototype.Destruct = function()
{
   this.rend.Kill();
   delete this.rend;
   this.gridrend.Kill();
   delete this.gridrend;
   delete this.doorrendList;
   this.selrend.Kill();
   delete this.selrend;
   gfx.DestroyMC(this.pointer);
   delete this.pointer;
   gfx.DestroyMC(this.objMenuMC);
   delete this.objMenuMC;
   gfx.DestroyMC(this.tileMenuMC);
   delete this.tileMenuMC;
   for(var _loc2_ in this.objList)
   {
      gfx.DestroyMC(this.objList[_loc2_][EDITRECORD_MC]);
      gfx.DestroyMC(this.objList[_loc2_][EDITRECORD_MC2]);
      delete this.objList[_loc2_];
   }
   delete this.objList;
};
NinjaEditor.prototype.Start = function()
{
   this.rend.Show();
   this.gridrend.Show();
   this.selrend.Show();
   this.gridmode = 0;
   this.MUST_BUILD_EDIT_OBJS = true;
   for(var _loc2_ in this.objList)
   {
      this.objList[_loc2_][EDITRECORD_MC]._visible = true;
      this.objList[_loc2_][EDITRECORD_MC2]._visible = true;
   }
   this.StartEditMenu();
};
NinjaEditor.prototype.Exit = function()
{
   this.rend.Clear();
   this.gridrend.Clear();
   this.selrend.Clear();
   this.rend.Hide();
   this.gridrend.Hide();
   this.selrend.Hide();
   this.pointer._visible = false;
   this.objMenuMC._visible = false;
   this.tileMenuMC_visible = false;
   this.SetTxtBox(this.DumpData());
   this.MUST_BUILD_EDIT_OBJS = false;
   this.SpawnGameObjects();
   for(var _loc3_ in this.objList)
   {
      this.objList[_loc3_][EDITRECORD_MC]._visible = false;
      this.objList[_loc3_][EDITRECORD_MC2]._visible = false;
   }
   var _loc2_;
   for(_loc3_ in this.objList)
   {
      _loc2_ = this.objList.pop();
      gfx.DestroyMC(_loc2_[EDITRECORD_MC]);
      DestroyMC(_loc2_[EDITRECORD_MC2]);
      false;
   }
};
NinjaEditor.prototype.SetTxtBox = function(str)
{
   gui.SetTxt(TXTBOX_TOP,str);
};
NinjaEditor.prototype.GetTxtBox = function()
{
   var _loc1_ = gui.GetTxt(TXTBOX_TOP);
   return _loc1_;
};
NinjaEditor.prototype.DumpData = function()
{
   this.SpawnGameObjects();
   var _loc2_ = game.DumpLevelData();
   objects.Clear();
   return _loc2_;
};
NinjaEditor.prototype.LoadData = function(levStr)
{
   this.MUST_BUILD_EDIT_OBJS = true;
   App_LoadLevel_Raw(levStr,App_StartEditor);
};
NinjaEditor.prototype.LoadObjData = function(objStr)
{
   var _loc3_;
   for(var _loc5_ in this.objList)
   {
      _loc3_ = this.objList.pop();
      gfx.DestroyMC(_loc3_[EDITRECORD_MC]);
      DestroyMC(_loc3_[EDITRECORD_MC2]);
      false;
   }
   objects.Clear();
   this.objStr = objStr;
   var _loc4_;
   if(0 >= this.objStr.length)
   {
      this.CURRENT_OBJ_LOADING = 0;
      return undefined;
   }
   _loc4_ = this.objStr.split(OBJECT_SEPERATION_CHAR);
   this.CURRENT_OBJ_LOADING = 0;
   var _loc2_;
   while(this.CURRENT_OBJ_LOADING < _loc4_.length)
   {
      _loc3_ = _loc4_[this.CURRENT_OBJ_LOADING].split(OBJTYPE_SEPERATION_CHAR);
      _loc2_ = _loc3_[1].split(OBJPARAM_SEPERATION_CHAR);
      for(_loc5_ in _loc2_)
      {
         _loc2_[_loc5_] = Number(_loc2_[_loc5_]);
      }
      this.BuildEditObj(Number(_loc3_[0]),_loc2_);
      this.CURRENT_OBJ_LOADING = this.CURRENT_OBJ_LOADING + 1;
   }
};
NinjaEditor.prototype.StartEditMenu = function()
{
   this.StopEdit();
   this.Tick = this.TickEditMenu;
   gui.Display(GUI_TEMP_EDITOR);
};
NinjaEditor.prototype.TickEditMenu = function()
{
   if(this.MUST_BUILD_EDIT_OBJS)
   {
      this.MUST_BUILD_EDIT_OBJS = false;
      this.LoadObjData(game.DumpObjData());
   }
   var _loc2_;
   if(Key.isDown(192) || Key.isDown(220))
   {
      APP_KEY_TRIG = false;
      this.Exit();
      _loc2_ = gui.GetTxt(TXTBOX_TOP);
      App_LoadLevel_Raw(_loc2_,App_StartDebugMenu);
      return undefined;
   }
   if(Key.isDown(33))
   {
      this.LoadData(this.GetTxtBox());
   }
   else if(Key.isDown(34))
   {
      this.SetTxtBox(this.DumpData());
   }
   else if(Key.isDown(45) || Key.isDown(96))
   {
      this.StopEdit();
      this.StartEditObjects();
   }
   else if(Key.isDown(46) || Key.isDown(110))
   {
      this.StopEdit();
      this.StartEditTiles();
   }
};
NinjaEditor.prototype.TickGrid = function()
{
   if(Key.isDown(86) && this.gridmode != 0)
   {
      this.gridmode = 0;
      this.gridrend.Clear();
      this.gridrend.Hide();
   }
   else if(Key.isDown(70) && this.gridmode != 1)
   {
      this.gridmode = 1;
      this.gridrend.Clear();
      this.gridrend.Show();
      this.DrawGrid_1();
      this.DrawGrid_0();
   }
   else if(Key.isDown(76) && this.gridmode != 2)
   {
      this.gridmode = 2;
      this.gridrend.Clear();
      this.gridrend.Show();
      this.DrawGrid_2();
      this.DrawGrid_0();
      this.DrawGrid_0();
   }
   else if(Key.isDown(72) && this.gridmode != 3)
   {
      this.gridmode = 3;
      this.gridrend.Clear();
      this.gridrend.Show();
      this.DrawGrid_3();
      this.DrawGrid_0();
   }
   else if(Key.isDown(75) && this.gridmode != 4)
   {
      this.gridmode = 4;
      this.gridrend.Clear();
      this.gridrend.Show();
      this.DrawGrid_4();
      this.DrawGrid_0();
      this.DrawGrid_0();
   }
   else if(Key.isDown(74) && this.gridmode != 5)
   {
      this.gridmode = 5;
      this.gridrend.Clear();
      this.gridrend.Show();
      this.DrawGrid_5();
      this.DrawGrid_0();
   }
   else if(Key.isDown(71) && this.gridmode != 6)
   {
      this.gridmode = 6;
      this.gridrend.Clear();
      this.gridrend.Show();
      this.DrawGrid_6();
      this.DrawGrid_0();
   }
   else if(Key.isDown(66) && this.gridmode != 7)
   {
      this.gridmode = 7;
      this.gridrend.Clear();
      this.gridrend.Show();
      this.DrawGrid_7();
   }
   else if(Key.isDown(78) && this.gridmode != 8)
   {
      this.gridmode = 8;
      this.gridrend.Clear();
      this.gridrend.Show();
      this.DrawGrid_8();
   }
   else if(Key.isDown(77) && this.gridmode != 9)
   {
      this.gridmode = 9;
      this.gridrend.Clear();
      this.gridrend.Show();
      this.DrawGrid_9();
   }
};
NinjaEditor.prototype.DrawGrid_0 = function()
{
   var _loc2_ = APP_TILE_SCALE * 2;
   var _loc5_ = APP_NUM_GRIDCOLS + 2;
   var _loc6_ = APP_NUM_GRIDROWS + 2;
   var _loc8_ = _loc5_ * _loc2_;
   var _loc7_ = _loc6_ * _loc2_;
   this.gridrend.SetStyle(0,16777215,this.gridAlpha);
   var _loc10_ = Math.floor(_loc5_ / 2);
   var _loc9_ = Math.floor(_loc6_ / 2);
   var _loc4_ = _loc10_ * _loc2_;
   var _loc3_ = _loc9_ * _loc2_;
   this.gridrend.DrawLine_S(0,_loc3_,_loc8_,_loc3_);
   this.gridrend.DrawLine_S(_loc4_,0,_loc4_,_loc7_);
   this.gridrend.DrawLine_S(0,_loc3_ + _loc2_,_loc8_,_loc3_ + _loc2_);
   this.gridrend.DrawLine_S(_loc4_ + _loc2_,0,_loc4_ + _loc2_,_loc7_);
};
NinjaEditor.prototype.DrawGrid_1 = function()
{
   var _loc2_ = APP_TILE_SCALE * 2;
   var _loc10_ = APP_NUM_GRIDCOLS + 2;
   var _loc12_ = APP_NUM_GRIDROWS + 2;
   var _loc8_ = _loc10_ * _loc2_;
   var _loc7_ = _loc12_ * _loc2_;
   this.gridrend.SetStyle(0,11184810,this.gridAlpha);
   var _loc11_ = Math.floor(_loc10_ / 4);
   var _loc9_ = Math.floor(_loc12_ / 4);
   var _loc6_ = _loc11_ * _loc2_;
   var _loc4_ = _loc9_ * _loc2_;
   this.gridrend.DrawLine_S(0,_loc4_,_loc8_,_loc4_);
   this.gridrend.DrawLine_S(_loc6_,0,_loc6_,_loc7_);
   this.gridrend.DrawLine_S(0,_loc4_ + _loc2_,_loc8_,_loc4_ + _loc2_);
   this.gridrend.DrawLine_S(_loc6_ + _loc2_,0,_loc6_ + _loc2_,_loc7_);
   var _loc5_ = _loc11_ * 3 * _loc2_;
   var _loc3_ = _loc9_ * 3 * _loc2_;
   this.gridrend.DrawLine_S(0,_loc3_,_loc8_,_loc3_);
   this.gridrend.DrawLine_S(_loc5_,0,_loc5_,_loc7_);
   this.gridrend.DrawLine_S(0,_loc3_ + _loc2_,_loc8_,_loc3_ + _loc2_);
   this.gridrend.DrawLine_S(_loc5_ + _loc2_,0,_loc5_ + _loc2_,_loc7_);
};
NinjaEditor.prototype.DrawGrid_2 = function()
{
   var _loc4_ = APP_TILE_SCALE * 2;
   var _loc8_ = APP_NUM_GRIDCOLS + 2;
   var _loc9_ = APP_NUM_GRIDROWS + 2;
   var _loc11_ = _loc8_ * _loc4_;
   var _loc10_ = _loc9_ * _loc4_;
   var _loc2_ = 0;
   var _loc5_;
   var _loc3_;
   var _loc7_;
   while(_loc2_ < _loc8_)
   {
      _loc5_ = 0;
      if(_loc2_ < 16)
      {
         _loc5_ = 1;
      }
      _loc3_ = 0;
      if((_loc2_ + _loc5_) % 2 == 0)
      {
         this.gridrend.SetStyle(0,11184810,this.gridAlpha);
      }
      else
      {
         this.gridrend.SetStyle(0,14540253,this.gridAlpha);
         _loc3_ = _loc4_;
      }
      _loc7_ = _loc2_ * _loc4_;
      this.gridrend.DrawLine_S(_loc7_,_loc3_,_loc7_,_loc10_ - _loc3_);
      _loc2_ = _loc2_ + 1;
   }
   _loc2_ = 0;
   var _loc6_;
   while(_loc2_ < _loc9_)
   {
      _loc5_ = 0;
      if(_loc2_ < 12)
      {
         _loc5_ = 1;
      }
      _loc3_ = 0;
      if((_loc2_ + _loc5_) % 2 == 0)
      {
         this.gridrend.SetStyle(0,11184810,this.gridAlpha);
      }
      else
      {
         this.gridrend.SetStyle(0,14540253,this.gridAlpha);
         _loc3_ = _loc4_;
      }
      _loc6_ = _loc2_ * _loc4_;
      this.gridrend.DrawLine_S(_loc3_,_loc6_,_loc11_ - _loc3_,_loc6_);
      _loc2_ = _loc2_ + 1;
   }
};
NinjaEditor.prototype.DrawGrid_3 = function()
{
   var _loc2_ = APP_TILE_SCALE * 2;
   var _loc10_ = APP_NUM_GRIDCOLS + 2;
   var _loc11_ = APP_NUM_GRIDROWS + 2;
   var _loc9_ = _loc10_ * _loc2_;
   var _loc8_ = _loc11_ * _loc2_;
   this.gridrend.SetStyle(0,11184810,this.gridAlpha);
   var _loc6_ = new Array();
   _loc6_[1] = 1;
   _loc6_[3] = 2;
   _loc6_[5] = 1;
   _loc6_[7] = 2;
   _loc6_[9] = 1;
   _loc6_[11] = 2;
   _loc6_[13] = 1;
   _loc6_[15] = 2;
   _loc6_[17] = 2;
   _loc6_[19] = 1;
   _loc6_[21] = 2;
   _loc6_[23] = 1;
   _loc6_[25] = 2;
   _loc6_[27] = 1;
   _loc6_[29] = 2;
   _loc6_[31] = 1;
   var _loc7_ = new Array();
   _loc7_[1] = 1;
   _loc7_[3] = 2;
   _loc7_[5] = 1;
   _loc7_[7] = 2;
   _loc7_[9] = 1;
   _loc7_[11] = 2;
   _loc7_[13] = 2;
   _loc7_[15] = 1;
   _loc7_[17] = 2;
   _loc7_[19] = 1;
   _loc7_[21] = 2;
   _loc7_[23] = 1;
   var _loc3_ = 0;
   var _loc5_;
   while(_loc3_ < _loc10_)
   {
      if(_loc6_[_loc3_] == 1)
      {
         _loc5_ = _loc3_ * _loc2_;
         this.gridrend.DrawLine_S(_loc5_,0,_loc5_,_loc8_);
         this.gridrend.DrawLine_S(_loc5_ + _loc2_,0,_loc5_ + _loc2_,_loc8_);
      }
      _loc3_ = _loc3_ + 1;
   }
   _loc3_ = 0;
   var _loc4_;
   while(_loc3_ < _loc11_)
   {
      if(_loc7_[_loc3_] == 1)
      {
         _loc4_ = _loc3_ * _loc2_;
         this.gridrend.DrawLine_S(0,_loc4_,_loc9_,_loc4_);
         this.gridrend.DrawLine_S(0,_loc4_ + _loc2_,_loc9_,_loc4_ + _loc2_);
      }
      _loc3_ = _loc3_ + 1;
   }
};
NinjaEditor.prototype.DrawGrid_4 = function()
{
   var _loc2_ = APP_TILE_SCALE * 2;
   var _loc10_ = APP_NUM_GRIDCOLS + 2;
   var _loc11_ = APP_NUM_GRIDROWS + 2;
   var _loc9_ = _loc10_ * _loc2_;
   var _loc8_ = _loc11_ * _loc2_;
   this.gridrend.SetStyle(0,11184810,this.gridAlpha);
   var _loc6_ = new Array();
   _loc6_[1] = 1;
   _loc6_[3] = 2;
   _loc6_[5] = 1;
   _loc6_[7] = 2;
   _loc6_[9] = 1;
   _loc6_[11] = 2;
   _loc6_[13] = 1;
   _loc6_[15] = 2;
   _loc6_[17] = 2;
   _loc6_[19] = 1;
   _loc6_[21] = 2;
   _loc6_[23] = 1;
   _loc6_[25] = 2;
   _loc6_[27] = 1;
   _loc6_[29] = 2;
   _loc6_[31] = 1;
   var _loc7_ = new Array();
   _loc7_[1] = 1;
   _loc7_[3] = 2;
   _loc7_[5] = 1;
   _loc7_[7] = 2;
   _loc7_[9] = 1;
   _loc7_[11] = 2;
   _loc7_[13] = 2;
   _loc7_[15] = 1;
   _loc7_[17] = 2;
   _loc7_[19] = 1;
   _loc7_[21] = 2;
   _loc7_[23] = 1;
   var _loc3_ = 0;
   var _loc5_;
   while(_loc3_ < _loc10_)
   {
      if(_loc6_[_loc3_] == 2)
      {
         _loc5_ = _loc3_ * _loc2_;
         this.gridrend.DrawLine_S(_loc5_,0,_loc5_,_loc8_);
         this.gridrend.DrawLine_S(_loc5_ + _loc2_,0,_loc5_ + _loc2_,_loc8_);
      }
      _loc3_ = _loc3_ + 1;
   }
   _loc3_ = 0;
   var _loc4_;
   while(_loc3_ < _loc11_)
   {
      if(_loc7_[_loc3_] == 2)
      {
         _loc4_ = _loc3_ * _loc2_;
         this.gridrend.DrawLine_S(0,_loc4_,_loc9_,_loc4_);
         this.gridrend.DrawLine_S(0,_loc4_ + _loc2_,_loc9_,_loc4_ + _loc2_);
      }
      _loc3_ = _loc3_ + 1;
   }
};
NinjaEditor.prototype.DrawGrid_5 = function()
{
   var _loc2_ = APP_TILE_SCALE * 2;
   var _loc10_ = APP_NUM_GRIDCOLS + 2;
   var _loc11_ = APP_NUM_GRIDROWS + 2;
   var _loc9_ = _loc10_ * _loc2_;
   var _loc8_ = _loc11_ * _loc2_;
   this.gridrend.SetStyle(0,11184810,this.gridAlpha);
   var _loc6_ = new Array();
   _loc6_[0] = 1;
   _loc6_[2] = 2;
   _loc6_[4] = 1;
   _loc6_[6] = 2;
   _loc6_[8] = 1;
   _loc6_[10] = 2;
   _loc6_[12] = 1;
   _loc6_[14] = 2;
   _loc6_[18] = 2;
   _loc6_[20] = 1;
   _loc6_[22] = 2;
   _loc6_[24] = 1;
   _loc6_[26] = 2;
   _loc6_[28] = 1;
   _loc6_[30] = 2;
   _loc6_[32] = 1;
   var _loc7_ = new Array();
   _loc7_[0] = 1;
   _loc7_[2] = 2;
   _loc7_[4] = 1;
   _loc7_[6] = 2;
   _loc7_[8] = 1;
   _loc7_[10] = 2;
   _loc7_[14] = 2;
   _loc7_[16] = 1;
   _loc7_[18] = 2;
   _loc7_[20] = 1;
   _loc7_[22] = 2;
   _loc7_[24] = 1;
   var _loc3_ = 0;
   var _loc5_;
   while(_loc3_ < _loc10_)
   {
      if(_loc6_[_loc3_] == 2)
      {
         _loc5_ = _loc3_ * _loc2_;
         this.gridrend.DrawLine_S(_loc5_,0,_loc5_,_loc8_);
         this.gridrend.DrawLine_S(_loc5_ + _loc2_,0,_loc5_ + _loc2_,_loc8_);
      }
      _loc3_ = _loc3_ + 1;
   }
   _loc3_ = 0;
   var _loc4_;
   while(_loc3_ < _loc11_)
   {
      if(_loc7_[_loc3_] == 2)
      {
         _loc4_ = _loc3_ * _loc2_;
         this.gridrend.DrawLine_S(0,_loc4_,_loc9_,_loc4_);
         this.gridrend.DrawLine_S(0,_loc4_ + _loc2_,_loc9_,_loc4_ + _loc2_);
      }
      _loc3_ = _loc3_ + 1;
   }
};
NinjaEditor.prototype.DrawGrid_6 = function()
{
   var _loc2_ = APP_TILE_SCALE * 2;
   var _loc10_ = APP_NUM_GRIDCOLS + 2;
   var _loc11_ = APP_NUM_GRIDROWS + 2;
   var _loc9_ = _loc10_ * _loc2_;
   var _loc8_ = _loc11_ * _loc2_;
   this.gridrend.SetStyle(0,11184810,this.gridAlpha);
   var _loc6_ = new Array();
   _loc6_[0] = 1;
   _loc6_[2] = 2;
   _loc6_[4] = 1;
   _loc6_[6] = 2;
   _loc6_[8] = 1;
   _loc6_[10] = 2;
   _loc6_[12] = 1;
   _loc6_[14] = 2;
   _loc6_[18] = 2;
   _loc6_[20] = 1;
   _loc6_[22] = 2;
   _loc6_[24] = 1;
   _loc6_[26] = 2;
   _loc6_[28] = 1;
   _loc6_[30] = 2;
   _loc6_[32] = 1;
   var _loc7_ = new Array();
   _loc7_[0] = 1;
   _loc7_[2] = 2;
   _loc7_[4] = 1;
   _loc7_[6] = 2;
   _loc7_[8] = 1;
   _loc7_[10] = 2;
   _loc7_[14] = 2;
   _loc7_[16] = 1;
   _loc7_[18] = 2;
   _loc7_[20] = 1;
   _loc7_[22] = 2;
   _loc7_[24] = 1;
   var _loc3_ = 0;
   var _loc5_;
   while(_loc3_ < _loc10_)
   {
      if(_loc6_[_loc3_] == 1)
      {
         _loc5_ = _loc3_ * _loc2_;
         this.gridrend.DrawLine_S(_loc5_,0,_loc5_,_loc8_);
         this.gridrend.DrawLine_S(_loc5_ + _loc2_,0,_loc5_ + _loc2_,_loc8_);
      }
      _loc3_ = _loc3_ + 1;
   }
   _loc3_ = 0;
   var _loc4_;
   while(_loc3_ < _loc11_)
   {
      if(_loc7_[_loc3_] == 1)
      {
         _loc4_ = _loc3_ * _loc2_;
         this.gridrend.DrawLine_S(0,_loc4_,_loc9_,_loc4_);
         this.gridrend.DrawLine_S(0,_loc4_ + _loc2_,_loc9_,_loc4_ + _loc2_);
      }
      _loc3_ = _loc3_ + 1;
   }
};
NinjaEditor.prototype.DrawGrid_7 = function()
{
   var _loc5_ = APP_TILE_SCALE * 2;
   var _loc11_ = APP_NUM_GRIDCOLS + 2;
   var _loc12_ = APP_NUM_GRIDROWS + 2;
   var _loc10_ = _loc11_ * _loc5_;
   var _loc9_ = _loc12_ * _loc5_;
   this.gridrend.SetStyle(0,16777215,this.gridAlpha);
   var _loc8_ = _loc10_ / 2;
   var _loc7_ = _loc9_ / 2;
   this.gridrend.DrawLine_S(0,_loc7_,_loc10_,_loc7_);
   this.gridrend.DrawLine_S(_loc8_,0,_loc8_,_loc9_);
   var _loc3_ = new Array();
   _loc3_[1] = 1;
   _loc3_[3] = 2;
   _loc3_[5] = 1;
   _loc3_[7] = 2;
   _loc3_[9] = 1;
   _loc3_[11] = 2;
   _loc3_[13] = 1;
   _loc3_[15] = 2;
   _loc3_[17] = 2;
   _loc3_[19] = 1;
   _loc3_[21] = 2;
   _loc3_[23] = 1;
   _loc3_[25] = 2;
   _loc3_[27] = 1;
   _loc3_[29] = 2;
   _loc3_[31] = 1;
   var _loc6_ = new Array();
   _loc6_[1] = 1;
   _loc6_[3] = 2;
   _loc6_[5] = 1;
   _loc6_[7] = 2;
   _loc6_[9] = 1;
   _loc6_[11] = 2;
   _loc6_[13] = 2;
   _loc6_[15] = 1;
   _loc6_[17] = 2;
   _loc6_[19] = 1;
   _loc6_[21] = 2;
   _loc6_[23] = 1;
   var _loc2_ = 0;
   var _loc4_;
   for(; _loc2_ < _loc11_; _loc2_ = _loc2_ + 1)
   {
      _loc4_ = 0;
      if(_loc3_[_loc2_] == 1)
      {
         this.gridrend.SetStyle(0,14540253,this.gridAlpha);
         _loc4_ = _loc5_;
      }
      else
      {
         if(_loc3_[_loc2_] != 2)
         {
            continue;
         }
         this.gridrend.SetStyle(0,11184810,this.gridAlpha);
      }
      _loc8_ = _loc2_ * _loc5_ + APP_TILE_SCALE;
      this.gridrend.DrawLine_S(_loc8_,_loc4_,_loc8_,_loc9_ - _loc4_);
   }
   _loc2_ = 0;
   for(; _loc2_ < _loc12_; _loc2_ = _loc2_ + 1)
   {
      _loc4_ = 0;
      if(_loc6_[_loc2_] == 1)
      {
         this.gridrend.SetStyle(0,14540253,this.gridAlpha);
         _loc4_ = _loc5_;
      }
      else
      {
         if(_loc6_[_loc2_] != 2)
         {
            continue;
         }
         this.gridrend.SetStyle(0,11184810,this.gridAlpha);
      }
      _loc7_ = _loc2_ * _loc5_ + APP_TILE_SCALE;
      this.gridrend.DrawLine_S(_loc4_,_loc7_,_loc10_ - _loc4_,_loc7_);
   }
};
NinjaEditor.prototype.DrawGrid_8 = function()
{
   var _loc5_ = APP_TILE_SCALE * 2;
   var _loc11_ = APP_NUM_GRIDCOLS + 2;
   var _loc12_ = APP_NUM_GRIDROWS + 2;
   var _loc10_ = _loc11_ * _loc5_;
   var _loc9_ = _loc12_ * _loc5_;
   this.gridrend.SetStyle(0,16777215,this.gridAlpha);
   var _loc8_ = _loc10_ / 2;
   var _loc7_ = _loc9_ / 2;
   this.gridrend.DrawLine_S(0,_loc7_,_loc10_,_loc7_);
   this.gridrend.DrawLine_S(_loc8_,0,_loc8_,_loc9_);
   var _loc3_ = new Array();
   _loc3_[0] = 1;
   _loc3_[2] = 2;
   _loc3_[4] = 1;
   _loc3_[6] = 2;
   _loc3_[8] = 1;
   _loc3_[10] = 2;
   _loc3_[12] = 1;
   _loc3_[14] = 2;
   _loc3_[18] = 2;
   _loc3_[20] = 1;
   _loc3_[22] = 2;
   _loc3_[24] = 1;
   _loc3_[26] = 2;
   _loc3_[28] = 1;
   _loc3_[30] = 2;
   _loc3_[32] = 1;
   var _loc6_ = new Array();
   _loc6_[0] = 1;
   _loc6_[2] = 2;
   _loc6_[4] = 1;
   _loc6_[6] = 2;
   _loc6_[8] = 1;
   _loc6_[10] = 2;
   _loc6_[14] = 2;
   _loc6_[16] = 1;
   _loc6_[18] = 2;
   _loc6_[20] = 1;
   _loc6_[22] = 2;
   _loc6_[24] = 1;
   var _loc2_ = 1;
   var _loc4_;
   for(; _loc2_ < _loc11_ - 1; _loc2_ = _loc2_ + 1)
   {
      _loc4_ = 0;
      if(_loc3_[_loc2_] == 1)
      {
         this.gridrend.SetStyle(0,14540253,this.gridAlpha);
         _loc4_ = _loc5_;
      }
      else
      {
         if(_loc3_[_loc2_] != 2)
         {
            continue;
         }
         this.gridrend.SetStyle(0,11184810,this.gridAlpha);
      }
      _loc8_ = _loc2_ * _loc5_ + APP_TILE_SCALE;
      this.gridrend.DrawLine_S(_loc8_,_loc4_,_loc8_,_loc9_ - _loc4_);
   }
   _loc2_ = 1;
   for(; _loc2_ < _loc12_ - 1; _loc2_ = _loc2_ + 1)
   {
      _loc4_ = 0;
      if(_loc6_[_loc2_] == 1)
      {
         this.gridrend.SetStyle(0,14540253,this.gridAlpha);
         _loc4_ = _loc5_;
      }
      else
      {
         if(_loc6_[_loc2_] != 2)
         {
            continue;
         }
         this.gridrend.SetStyle(0,11184810,this.gridAlpha);
      }
      _loc7_ = _loc2_ * _loc5_ + APP_TILE_SCALE;
      this.gridrend.DrawLine_S(_loc4_,_loc7_,_loc10_ - _loc4_,_loc7_);
   }
};
NinjaEditor.prototype.DrawGrid_9 = function()
{
   var _loc4_ = APP_TILE_SCALE * 2;
   var _loc7_ = APP_NUM_GRIDCOLS + 2;
   var _loc8_ = APP_NUM_GRIDROWS + 2;
   var _loc6_ = _loc7_ * _loc4_;
   var _loc5_ = _loc8_ * _loc4_;
   var _loc2_ = 1;
   var _loc3_;
   var _loc10_;
   while(_loc2_ < _loc7_ - 1)
   {
      _loc3_ = 0;
      if(_loc2_ % 2 == 0)
      {
         this.gridrend.SetStyle(0,11184810,this.gridAlpha);
      }
      else
      {
         this.gridrend.SetStyle(0,14540253,this.gridAlpha);
         _loc3_ = _loc4_;
      }
      _loc10_ = _loc2_ * _loc4_ + APP_TILE_SCALE;
      this.gridrend.DrawLine_S(_loc10_,_loc3_,_loc10_,_loc5_ - _loc3_);
      _loc2_ = _loc2_ + 1;
   }
   _loc2_ = 1;
   var _loc9_;
   while(_loc2_ < _loc8_ - 1)
   {
      _loc3_ = 0;
      if(_loc2_ % 2 == 0)
      {
         this.gridrend.SetStyle(0,11184810,this.gridAlpha);
      }
      else
      {
         this.gridrend.SetStyle(0,14540253,this.gridAlpha);
         _loc3_ = _loc4_;
      }
      _loc9_ = _loc2_ * _loc4_ + APP_TILE_SCALE;
      this.gridrend.DrawLine_S(_loc3_,_loc9_,_loc6_ - _loc3_,_loc9_);
      _loc2_ = _loc2_ + 1;
   }
   this.gridrend.SetStyle(0,16777215,this.gridAlpha);
   _loc10_ = _loc6_ / 2;
   _loc9_ = _loc5_ / 2;
   this.gridrend.DrawLine_S(0,_loc9_,_loc6_,_loc9_);
   this.gridrend.DrawLine_S(_loc10_,0,_loc10_,_loc5_);
   this.gridrend.DrawLine_S(0,_loc9_,_loc6_,_loc9_);
   this.gridrend.DrawLine_S(_loc10_,0,_loc10_,_loc5_);
};
