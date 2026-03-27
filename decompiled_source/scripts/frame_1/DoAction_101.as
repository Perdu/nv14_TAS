NinjaEditor.prototype.StartEditObjects = function()
{
   gui.Display(GUI_OBJ_EDITOR);
   gui.HideTxt();
   this.objSnapTo = tiles.xw;
   this.pointer.txt = "(1/2 snap)";
   this.pointer._visible = true;
   this.objMenuMC._visible = true;
   this.tileMenuMC._visible = false;
   this.pointer.objhelp._visible = true;
   this.pointer.tilehelp._visible = false;
   this.Tick = this.TickEditObjects;
   this.StopEdit = this.StopEditObjects;
   this.currentEOBJTYPE = Number(0);
   this.currentOBJTYPE = this.objTypes[0];
   this.editObjStep = 0;
   this.pointer.objhelp.gotoAndStop(this.currentEOBJTYPE + 1);
   this.RefreshObjMenu();
};
NinjaEditor.prototype.StopEditObjects = function()
{
   this.pointer._visible = false;
   this.objMenuMC._visible = false;
   this.tileMenuMC._visible = false;
};
NinjaEditor.prototype.RefreshObjMenu = function()
{
   var _loc2_ = input.getMousePos();
   if(_loc2_.x < 400)
   {
      this.objMenuMC._x = 400;
   }
   else
   {
      this.objMenuMC._x = 0;
   }
   if(_loc2_.y < 300)
   {
      this.objMenuMC._y = 450;
   }
   else
   {
      this.objMenuMC._y = 150;
   }
};
NinjaEditor.prototype.TickEditObjects = function()
{
   this.TickGrid();
   if(Key.isDown(36))
   {
      this.StartEditMenu();
      return undefined;
   }
   if(Key.isDown(46) || Key.isDown(110))
   {
      this.StopEdit();
      this.StartEditTiles();
   }
   m = input.getMousePos();
   if(Key.isDown(90))
   {
      this.objSnapTo = 1;
      this.pointer.txt = "(no snap)";
   }
   else if(Key.isDown(88))
   {
      this.objSnapTo = tiles.xw;
      this.pointer.txt = "(1/2 snap)";
   }
   else if(Key.isDown(67))
   {
      this.objSnapTo = tiles.xw * 0.5;
      this.pointer.txt = "(1/4 snap)";
   }
   if(Key.isDown(82))
   {
      this.doortrigsvis = false;
      for(var _loc6_ in this.doorrendList)
      {
         this.doorrendList[_loc6_]._visible = false;
      }
   }
   else if(Key.isDown(84))
   {
      this.doortrigsvis = true;
      for(_loc6_ in this.doorrendList)
      {
         this.doorrendList[_loc6_]._visible = true;
      }
   }
   var _loc2_ = new Vector2(Math.round(m.x / this.objSnapTo) * this.objSnapTo,Math.round(m.y / this.objSnapTo) * this.objSnapTo);
   this.pointer._x = _loc2_.x;
   this.pointer._y = _loc2_.y;
   var _loc7_ = tiles.GetTile_V(_loc2_);
   this.rend.Clear();
   this.rend.SetStyle(0,0,30);
   this.rend.DrawAABB(_loc7_.pos,_loc7_.xw,_loc7_.yw);
   this.RefreshObjMenu();
   for(_loc6_ in this.setObjTypeKeys)
   {
      if(Key.isDown(this.setObjTypeKeys[_loc6_]))
      {
         this.currentEOBJTYPE = Number(_loc6_);
         this.currentOBJTYPE = this.objTypes[_loc6_];
         this.editObjStep = 0;
         this.pointer.objhelp.gotoAndStop(this.currentEOBJTYPE + 1);
         break;
      }
   }
   var _loc3_;
   var _loc5_;
   var _loc4_;
   var _loc8_;
   var _loc9_;
   var _loc10_;
   var _loc11_;
   var _loc12_;
   if(input.MousePressed())
   {
      if(Key.isDown(8))
      {
         this.KillNearestObj(m);
         return undefined;
      }
      if(Key.isDown(220))
      {
         this.KillMostRecentObj();
         return undefined;
      }
      delete params;
      _loc3_ = 2;
      var params = new Array();
      params[0] = _loc2_.x;
      params[1] = _loc2_.y;
      if(this.currentEOBJTYPE == EOBJTYPE_FLOORGUARD)
      {
         params[2] = 1;
         _loc3_ = 3;
      }
      else if(this.currentEOBJTYPE == EOBJTYPE_ONEWAYPLATFORM)
      {
         if(Key.isDown(83))
         {
            params[2] = AI_DIR_D;
         }
         else if(Key.isDown(87))
         {
            params[2] = AI_DIR_U;
         }
         else if(Key.isDown(65))
         {
            params[2] = AI_DIR_L;
         }
         else
         {
            if(!Key.isDown(68))
            {
               return undefined;
            }
            params[2] = AI_DIR_R;
         }
         _loc3_ = 3;
      }
      else if(this.currentEOBJTYPE == EOBJTYPE_THWOMP)
      {
         if(Key.isDown(83))
         {
            params[2] = AI_DIR_D;
         }
         else if(Key.isDown(87))
         {
            params[2] = AI_DIR_U;
         }
         else if(Key.isDown(65))
         {
            params[2] = AI_DIR_L;
         }
         else
         {
            if(!Key.isDown(68))
            {
               return undefined;
            }
            params[2] = AI_DIR_R;
         }
         _loc3_ = 3;
      }
      else if(this.currentEOBJTYPE == EOBJTYPE_LAUNCHPAD)
      {
         _loc5_ = 0;
         _loc4_ = 0;
         if(Key.isDown(87))
         {
            _loc4_ = -1;
         }
         else if(Key.isDown(83))
         {
            _loc4_ = 1;
         }
         if(Key.isDown(65))
         {
            _loc5_ = -1;
         }
         else if(Key.isDown(68))
         {
            _loc5_ = 1;
         }
         _loc8_ = Math.sqrt(_loc5_ * _loc5_ + _loc4_ * _loc4_);
         if(_loc8_ == 0)
         {
            return undefined;
         }
         _loc5_ /= _loc8_;
         _loc4_ /= _loc8_;
         params[2] = _loc5_;
         params[3] = _loc4_;
         _loc3_ = 4;
      }
      else if(this.currentEOBJTYPE == EOBJTYPE_EXIT)
      {
         if(this.editObjStep == 0)
         {
            this.editObjStepVar0 = new Vector2(_loc2_.x,_loc2_.y);
            this.editObjStep = 1;
            this.pointer.objhelp.gotoAndStop(18);
            return undefined;
         }
         if(this.editObjStep == 1)
         {
            params[0] = this.editObjStepVar0.x;
            params[1] = this.editObjStepVar0.y;
            params[2] = _loc2_.x;
            params[3] = _loc2_.y;
            this.pointer.objhelp.gotoAndStop(10);
            _loc3_ = 4;
         }
      }
      else if(this.currentEOBJTYPE == EOBJTYPE_TREKDOOR)
      {
         _loc9_ = tiles.GetTile_V(_loc2_);
         params[4] = _loc9_.i;
         params[5] = _loc9_.j;
         params[3] = 0;
         params[0] = _loc2_.x;
         params[1] = _loc2_.y;
         params[6] = 0;
         if(Key.isDown(83))
         {
            params[2] = 1;
            params[7] = 0;
            params[8] = 0;
         }
         else if(Key.isDown(68))
         {
            params[2] = 0;
            params[7] = 0;
            params[8] = 0;
         }
         else if(Key.isDown(65))
         {
            params[7] = -1;
            params[8] = 0;
            params[2] = 0;
         }
         else
         {
            if(!Key.isDown(87))
            {
               return undefined;
            }
            params[7] = 0;
            params[8] = -1;
            params[2] = 1;
         }
         _loc3_ = 9;
      }
      else if(this.currentEOBJTYPE == EOBJTYPE_LOCKDOOR)
      {
         _loc9_ = tiles.GetTile_V(_loc2_);
         params[4] = _loc9_.i;
         params[5] = _loc9_.j;
         params[3] = 0;
         params[6] = 1;
         if(this.editObjStep == 0)
         {
            this.editObjStepVar0 = new Vector2(params[4],params[5]);
            this.editObjStepVarX = new Vector2(0,0);
            this.editObjStep = 1;
            if(Key.isDown(83))
            {
               this.editObjStepVar1 = 1;
            }
            else if(Key.isDown(68))
            {
               this.editObjStepVar1 = 0;
            }
            else if(Key.isDown(65))
            {
               this.editObjStepVarX.x = -1;
               this.editObjStepVar1 = 0;
            }
            else
            {
               if(!Key.isDown(87))
               {
                  this.editObjStep = 0;
                  return undefined;
               }
               this.editObjStepVarX.y = -1;
               this.editObjStepVar1 = 1;
            }
            this.pointer.objhelp.gotoAndStop(19);
            return undefined;
         }
         if(this.editObjStep == 1)
         {
            params[4] = this.editObjStepVar0.x;
            params[5] = this.editObjStepVar0.y;
            params[7] = this.editObjStepVarX.x;
            params[8] = this.editObjStepVarX.y;
            params[2] = this.editObjStepVar1;
            params[0] = _loc2_.x;
            params[1] = _loc2_.y;
            this.pointer.objhelp.gotoAndStop(13);
            _loc3_ = 9;
         }
      }
      else if(this.currentEOBJTYPE == EOBJTYPE_TRAPDOOR)
      {
         _loc9_ = tiles.GetTile_V(_loc2_);
         params[4] = _loc9_.i;
         params[5] = _loc9_.j;
         params[3] = 1;
         params[6] = 0;
         if(this.editObjStep == 0)
         {
            this.editObjStepVar0 = new Vector2(params[4],params[5]);
            this.editObjStepVarX = new Vector2(0,0);
            this.editObjStep = 1;
            if(Key.isDown(83))
            {
               this.editObjStepVar1 = 1;
            }
            else if(Key.isDown(68))
            {
               this.editObjStepVar1 = 0;
            }
            else if(Key.isDown(65))
            {
               this.editObjStepVarX.x = -1;
               this.editObjStepVar1 = 0;
            }
            else
            {
               if(!Key.isDown(87))
               {
                  this.editObjStep = 0;
                  return undefined;
               }
               this.editObjStepVarX.y = -1;
               this.editObjStepVar1 = 1;
            }
            this.pointer.objhelp.gotoAndStop(20);
            return undefined;
         }
         if(this.editObjStep == 1)
         {
            params[4] = this.editObjStepVar0.x;
            params[5] = this.editObjStepVar0.y;
            params[2] = this.editObjStepVar1;
            params[7] = this.editObjStepVarX.x;
            params[8] = this.editObjStepVarX.y;
            params[0] = _loc2_.x;
            params[1] = _loc2_.y;
            this.pointer.objhelp.gotoAndStop(14);
            _loc3_ = 9;
         }
      }
      else if(this.currentEOBJTYPE == EOBJTYPE_ZAPDRONE)
      {
         if(this.editObjStep == 0)
         {
            if(Key.isDown(81))
            {
               _loc10_ = DRONEMOVE_SURFACEFOLLOW_CCW;
            }
            else if(Key.isDown(69))
            {
               _loc10_ = DRONEMOVE_SURFACEFOLLOW_CW;
            }
            else if(Key.isDown(87))
            {
               _loc10_ = DRONEMOVE_WANDER_ALTERNATING;
            }
            else if(Key.isDown(83))
            {
               _loc10_ = DRONEMOVE_WANDER_RANDOM;
            }
            else if(Key.isDown(65))
            {
               _loc10_ = DRONEMOVE_WANDER_CCW;
            }
            else
            {
               if(!Key.isDown(68))
               {
                  return undefined;
               }
               _loc10_ = DRONEMOVE_WANDER_CW;
            }
            this.editObjStepVar0 = _loc10_;
            this.editObjStep = 1;
            this.pointer.objhelp.gotoAndStop(21);
            return undefined;
         }
         if(this.editObjStep == 1)
         {
            if(Key.isDown(68))
            {
               _loc11_ = AI_DIR_R;
            }
            else if(Key.isDown(65))
            {
               _loc11_ = AI_DIR_L;
            }
            else if(Key.isDown(87))
            {
               _loc11_ = AI_DIR_U;
            }
            else
            {
               if(!Key.isDown(83))
               {
                  this.editObjStep = 0;
                  this.pointer.objhelp.gotoAndStop(15);
                  return undefined;
               }
               _loc11_ = AI_DIR_D;
            }
            this.editObjStepVar1 = _loc11_;
            this.editObjStep = 2;
            this.pointer.objhelp.gotoAndStop(22);
            return undefined;
         }
         if(this.editObjStep == 2)
         {
            if(Key.isDown(32))
            {
               _loc12_ = 1;
            }
            else
            {
               _loc12_ = 0;
            }
            params[2] = this.editObjStepVar0;
            params[3] = _loc12_;
            params[4] = DRONEWEAP_ZAP;
            params[5] = this.editObjStepVar1;
            this.pointer.objhelp.gotoAndStop(15);
            _loc3_ = 6;
         }
      }
      else if(this.currentEOBJTYPE == EOBJTYPE_LASERDRONE)
      {
         if(this.editObjStep == 0)
         {
            if(Key.isDown(81))
            {
               _loc10_ = DRONEMOVE_SURFACEFOLLOW_CCW;
            }
            else if(Key.isDown(69))
            {
               _loc10_ = DRONEMOVE_SURFACEFOLLOW_CW;
            }
            else if(Key.isDown(87))
            {
               _loc10_ = DRONEMOVE_WANDER_ALTERNATING;
            }
            else if(Key.isDown(83))
            {
               _loc10_ = DRONEMOVE_WANDER_RANDOM;
            }
            else if(Key.isDown(65))
            {
               _loc10_ = DRONEMOVE_WANDER_CCW;
            }
            else
            {
               if(!Key.isDown(68))
               {
                  return undefined;
               }
               _loc10_ = DRONEMOVE_WANDER_CW;
            }
            this.editObjStepVar0 = _loc10_;
            this.editObjStep = 1;
            this.pointer.objhelp.gotoAndStop(23);
            return undefined;
         }
         if(this.editObjStep == 1)
         {
            if(Key.isDown(68))
            {
               _loc11_ = AI_DIR_R;
            }
            else if(Key.isDown(65))
            {
               _loc11_ = AI_DIR_L;
            }
            else if(Key.isDown(87))
            {
               _loc11_ = AI_DIR_U;
            }
            else
            {
               if(!Key.isDown(83))
               {
                  this.editObjStep = 0;
                  this.pointer.objhelp.gotoAndStop(16);
                  return undefined;
               }
               _loc11_ = AI_DIR_D;
            }
            this.editObjStepVar1 = _loc11_;
            this.editObjStep = 2;
            params[2] = this.editObjStepVar0;
            params[3] = _loc12_;
            params[4] = DRONEWEAP_LASER;
            params[5] = this.editObjStepVar1;
            this.pointer.objhelp.gotoAndStop(16);
            _loc3_ = 6;
         }
      }
      else if(this.currentEOBJTYPE == EOBJTYPE_CHAINGUNDRONE)
      {
         if(this.editObjStep == 0)
         {
            if(Key.isDown(81))
            {
               _loc10_ = DRONEMOVE_SURFACEFOLLOW_CCW;
            }
            else if(Key.isDown(69))
            {
               _loc10_ = DRONEMOVE_SURFACEFOLLOW_CW;
            }
            else if(Key.isDown(87))
            {
               _loc10_ = DRONEMOVE_WANDER_ALTERNATING;
            }
            else if(Key.isDown(83))
            {
               _loc10_ = DRONEMOVE_WANDER_RANDOM;
            }
            else if(Key.isDown(65))
            {
               _loc10_ = DRONEMOVE_WANDER_CCW;
            }
            else
            {
               if(!Key.isDown(68))
               {
                  return undefined;
               }
               _loc10_ = DRONEMOVE_WANDER_CW;
            }
            this.editObjStepVar0 = _loc10_;
            this.editObjStep = 1;
            this.pointer.objhelp.gotoAndStop(25);
            return undefined;
         }
         if(this.editObjStep == 1)
         {
            if(Key.isDown(68))
            {
               _loc11_ = AI_DIR_R;
            }
            else if(Key.isDown(65))
            {
               _loc11_ = AI_DIR_L;
            }
            else if(Key.isDown(87))
            {
               _loc11_ = AI_DIR_U;
            }
            else
            {
               if(!Key.isDown(83))
               {
                  this.editObjStep = 0;
                  this.pointer.objhelp.gotoAndStop(17);
                  return undefined;
               }
               _loc11_ = AI_DIR_D;
            }
            this.editObjStepVar1 = _loc11_;
            this.editObjStep = 2;
            if(Key.isDown(32))
            {
               _loc12_ = 1;
            }
            else
            {
               _loc12_ = 0;
            }
            params[2] = this.editObjStepVar0;
            params[3] = _loc12_;
            params[4] = DRONEWEAP_CHAINGUN;
            params[5] = this.editObjStepVar1;
            this.pointer.objhelp.gotoAndStop(17);
            _loc3_ = 6;
         }
      }
      else
      {
         _loc3_ = 2;
      }
      this.CreateObject(this.currentOBJTYPE,params,_loc3_,this.currentEOBJTYPE);
   }
};
NinjaEditor.prototype.KillMostRecentObj = function()
{
   var _loc2_ = this.objList.pop();
   gfx.DestroyMC(_loc2_[EDITRECORD_MC]);
   gfx.DestroyMC(_loc2_[EDITRECORD_MC2]);
   false;
};
NinjaEditor.prototype.KillNearestObj = function(p)
{
   var _loc11_ = tiles.GetTile_S(p.x,p.y);
   var _loc13_ = _loc11_.i;
   var _loc12_ = _loc11_.j;
   var _loc8_ = null;
   var _loc7_ = 10000000;
   var _loc9_ = -1;
   var _loc6_ = this.objList;
   var _loc14_;
   var _loc4_;
   var _loc3_;
   var _loc2_;
   for(var _loc10_ in _loc6_)
   {
      _loc14_ = _loc6_[_loc10_];
      _loc4_ = _loc14_[EDITRECORD_POS].x - p.x;
      _loc3_ = _loc14_[EDITRECORD_POS].y - p.y;
      _loc2_ = _loc4_ * _loc4_ + _loc3_ * _loc3_;
      if(300 >= _loc2_)
      {
         if(_loc2_ < _loc7_)
         {
            _loc9_ = _loc10_;
            _loc8_ = _loc14_;
            _loc7_ = _loc2_;
         }
      }
   }
   if(_loc8_ != null)
   {
      _loc14_ = this.objList.splice(_loc9_,1);
      gfx.DestroyMC(_loc8_[EDITRECORD_MC]);
      gfx.DestroyMC(_loc8_[EDITRECORD_MC2]);
      false;
   }
};
NinjaEditor.prototype.SpawnGameObjects = function()
{
   var _loc3_ = -1;
   for(var _loc2_ in this.objList)
   {
      if(this.objList[_loc2_][EDITRECORD_TYPE] == OBJTYPE_PLAYER)
      {
         _loc3_ = _loc2_;
         break;
      }
   }
   var _loc4_;
   if(_loc3_ >= 0)
   {
      _loc4_ = this.objList[_loc3_];
      this.objList.splice(_loc3_,1);
      this.objList.splice(0,0,_loc4_);
   }
   objects.Clear();
   var _loc2_ = 0;
   while(_loc2_ < this.objList.length)
   {
      objects.SpawnGameObject(this.objList[_loc2_][EDITRECORD_TYPE],this.objList[_loc2_][EDITRECORD_PARAMS]);
      _loc2_ = _loc2_ + 1;
   }
};
NinjaEditor.prototype.BuildEditObj = function(OBJTYPE, params)
{
   var _loc2_ = -1;
   if(OBJTYPE == OBJTYPE_GOLD)
   {
      _loc2_ = EOBJTYPE_GOLD;
   }
   else if(OBJTYPE == OBJTYPE_BOUNCEBLOCK)
   {
      _loc2_ = EOBJTYPE_BOUNCEBLOCK;
   }
   else if(OBJTYPE == OBJTYPE_LAUNCHPAD)
   {
      _loc2_ = EOBJTYPE_LAUNCHPAD;
   }
   else if(OBJTYPE == OBJTYPE_TURRET)
   {
      _loc2_ = EOBJTYPE_TURRET;
   }
   else if(OBJTYPE == OBJTYPE_FLOORGUARD)
   {
      _loc2_ = EOBJTYPE_FLOORGUARD;
   }
   else if(OBJTYPE == OBJTYPE_PLAYER)
   {
      _loc2_ = EOBJTYPE_PLAYER;
   }
   else if(OBJTYPE == OBJTYPE_MINE)
   {
      _loc2_ = EOBJTYPE_MINE;
   }
   else if(OBJTYPE == OBJTYPE_ONEWAYPLATFORM)
   {
      _loc2_ = EOBJTYPE_ONEWAYPLATFORM;
   }
   else if(OBJTYPE == OBJTYPE_THWOMP)
   {
      _loc2_ = EOBJTYPE_THWOMP;
   }
   else if(OBJTYPE == OBJTYPE_EXIT)
   {
      _loc2_ = EOBJTYPE_EXIT;
   }
   else if(OBJTYPE == OBJTYPE_HOMINGLAUNCHER)
   {
      _loc2_ = EOBJTYPE_HOMINGLAUNCHER;
   }
   else if(OBJTYPE == OBJTYPE_ONEWAYPLATFORM)
   {
      _loc2_ = EOBJTYPE_ONEWAYPLATFORM;
   }
   else if(OBJTYPE == OBJTYPE_TESTDOOR)
   {
      if(params[3] == 1 && params[6] == 0)
      {
         _loc2_ = EOBJTYPE_TRAPDOOR;
      }
      else if(params[3] == 0 && params[6] == 1)
      {
         _loc2_ = EOBJTYPE_LOCKDOOR;
      }
      else
      {
         if(!(params[3] == 0 && params[6] == 0))
         {
            return undefined;
         }
         _loc2_ = EOBJTYPE_TREKDOOR;
      }
   }
   else
   {
      if(OBJTYPE != OBJTYPE_DRONE)
      {
         return undefined;
      }
      if(params[4] == DRONEWEAP_ZAP)
      {
         _loc2_ = EOBJTYPE_ZAPDRONE;
      }
      else if(params[4] == DRONEWEAP_LASER)
      {
         _loc2_ = EOBJTYPE_LASERDRONE;
      }
      else
      {
         if(params[4] != DRONEWEAP_CHAINGUN)
         {
            return undefined;
         }
         _loc2_ = EOBJTYPE_CHAINGUNDRONE;
      }
   }
   this.CreateObject(OBJTYPE,params,params.length,_loc2_);
};
EDITRECORD_TYPE = 0;
EDITRECORD_PARAMS = 1;
EDITRECORD_POS = 2;
EDITRECORD_CELLI = 3;
EDITRECORD_CELLJ = 4;
EDITRECORD_MC = 5;
EDITRECORD_MC2 = 6;
NinjaEditor.prototype.CreateObject = function(OBJTYPE, params, plen, EOBJTYPE)
{
   this.editObjStep = 0;
   this.objnum = this.objnum + 1;
   var _loc8_ = params[0];
   var _loc7_ = params[1];
   var _loc6_ = tiles.GetTile_S(_loc8_,_loc7_);
   var _loc11_ = _loc6_.i;
   var _loc10_ = _loc6_.j;
   var _loc3_ = new Array();
   _loc3_[EDITRECORD_TYPE] = OBJTYPE;
   _loc3_[EDITRECORD_PARAMS] = new Array();
   var _loc2_ = 0;
   while(_loc2_ < plen)
   {
      _loc3_[EDITRECORD_PARAMS][_loc2_] = params[_loc2_];
      _loc2_ = _loc2_ + 1;
   }
   _loc3_[EDITRECORD_POS] = new Vector2(_loc8_,_loc7_);
   _loc3_[EDITRECORD_CELLI] = _loc11_;
   _loc3_[EDITRECORD_CELLJ] = _loc10_;
   var _loc9_ = gfx.CreateSprite("editorObjMC",LAYER_EDITOR);
   _loc3_[EDITRECORD_MC] = _loc9_;
   var _loc12_ = gfx.CreateSprite("editorObjMC",LAYER_EDITOR);
   _loc3_[EDITRECORD_MC2] = _loc12_;
   this.objList.push(_loc3_);
   this.DrawObject(_loc3_,EOBJTYPE);
};
NinjaEditor.prototype.DrawObject = function(defList, EOBJ_TYPE)
{
   var _loc12_ = defList[EDITRECORD_POS];
   var _loc2_ = defList[EDITRECORD_PARAMS];
   var _loc16_ = defList[EDITRECORD_CELLI];
   var _loc15_ = defList[EDITRECORD_CELLJ];
   var _loc13_ = defList[EDITRECORD_TYPE];
   var _loc4_ = defList[EDITRECORD_MC];
   var _loc3_ = defList[EDITRECORD_MC2];
   _loc4_.gotoAndStop(EOBJ_TYPE + 1);
   _loc4_._x = _loc12_.x;
   _loc4_._y = _loc12_.y;
   _loc4_._rotation = 0;
   _loc3_._rotation = 0;
   _loc3_.gotoAndStop(1);
   var _loc14_;
   var _loc11_;
   var _loc8_;
   var _loc10_;
   var _loc9_;
   var _loc6_;
   if(EOBJ_TYPE == EOBJTYPE_PLAYER)
   {
      _loc3_._visible = false;
   }
   else if(EOBJ_TYPE == EOBJTYPE_GOLD)
   {
      _loc3_._visible = false;
   }
   else if(EOBJ_TYPE == EOBJTYPE_BOUNCEBLOCK)
   {
      _loc3_._visible = false;
   }
   else if(EOBJ_TYPE == EOBJTYPE_LAUNCHPAD)
   {
      _loc3_._visible = false;
      _loc14_ = Math.atan2(_loc2_[3],_loc2_[2]);
      _loc4_._rotation = 90 + _loc14_ / 0.017453292519943295;
   }
   else if(EOBJ_TYPE == EOBJTYPE_TURRET)
   {
      _loc3_._visible = false;
   }
   else if(EOBJ_TYPE == EOBJTYPE_FLOORGUARD)
   {
      _loc3_._visible = false;
      _loc11_ = tiles.GetTile_S(_loc2_[0],_loc2_[1]);
      _loc2_[1] = _loc11_.pos.y + _loc11_.yw - 6;
      _loc4_._x = _loc2_[0];
      _loc4_._y = _loc2_[1];
   }
   else if(EOBJ_TYPE == EOBJTYPE_ZAPDRONE)
   {
      _loc11_ = tiles.GetTile_S(_loc2_[0],_loc2_[1]);
      _loc2_[0] = _loc11_.pos.x;
      _loc2_[1] = _loc11_.pos.y;
      _loc4_._x = _loc2_[0];
      _loc4_._y = _loc2_[1];
      if(_loc2_[3] == 1)
      {
         _loc4_.gotoAndStop(21);
      }
      _loc3_._x = _loc2_[0];
      _loc3_._y = _loc2_[1];
      _loc3_.gotoAndStop(22);
      if(_loc2_[5] == AI_DIR_U)
      {
         _loc3_._rotation = -90;
      }
      else if(_loc2_[5] == AI_DIR_L)
      {
         _loc3_._rotation = 180;
      }
      else if(_loc2_[5] == AI_DIR_R)
      {
         _loc3_._rotation = 0;
      }
      else
      {
         _loc3_._rotation = 90;
      }
      _loc3_._visible = true;
   }
   else if(EOBJ_TYPE == EOBJTYPE_LASERDRONE)
   {
      _loc11_ = tiles.GetTile_S(_loc2_[0],_loc2_[1]);
      _loc2_[0] = _loc11_.pos.x;
      _loc2_[1] = _loc11_.pos.y;
      _loc4_._x = _loc2_[0];
      _loc4_._y = _loc2_[1];
      _loc3_._x = _loc2_[0];
      _loc3_._y = _loc2_[1];
      _loc3_.gotoAndStop(22);
      if(_loc2_[5] == AI_DIR_U)
      {
         _loc3_._rotation = -90;
      }
      else if(_loc2_[5] == AI_DIR_L)
      {
         _loc3_._rotation = 180;
      }
      else if(_loc2_[5] == AI_DIR_R)
      {
         _loc3_._rotation = 0;
      }
      else
      {
         _loc3_._rotation = 90;
      }
      _loc3_._visible = true;
   }
   else if(EOBJ_TYPE == EOBJTYPE_CHAINGUNDRONE)
   {
      _loc11_ = tiles.GetTile_S(_loc2_[0],_loc2_[1]);
      _loc2_[0] = _loc11_.pos.x;
      _loc2_[1] = _loc11_.pos.y;
      _loc4_._x = _loc2_[0];
      _loc4_._y = _loc2_[1];
      _loc3_._x = _loc2_[0];
      _loc3_._y = _loc2_[1];
      _loc3_.gotoAndStop(22);
      if(_loc2_[5] == AI_DIR_U)
      {
         _loc3_._rotation = -90;
      }
      else if(_loc2_[5] == AI_DIR_L)
      {
         _loc3_._rotation = 180;
      }
      else if(_loc2_[5] == AI_DIR_R)
      {
         _loc3_._rotation = 0;
      }
      else
      {
         _loc3_._rotation = 90;
      }
      _loc3_._visible = true;
   }
   else if(EOBJ_TYPE == EOBJTYPE_ONEWAYPLATFORM)
   {
      _loc3_._visible = false;
      if(_loc2_[2] == AI_DIR_D)
      {
         _loc4_._rotation = 180;
      }
      else if(_loc2_[2] == AI_DIR_L)
      {
         _loc4_._rotation = -90;
      }
      else if(_loc2_[2] == AI_DIR_R)
      {
         _loc4_._rotation = 90;
      }
   }
   else if(EOBJ_TYPE == EOBJTYPE_THWOMP)
   {
      _loc3_._visible = false;
      if(_loc2_[2] == AI_DIR_U)
      {
         _loc4_._rotation = 180;
      }
      else if(_loc2_[2] == AI_DIR_L)
      {
         _loc4_._rotation = 90;
      }
      else if(_loc2_[2] == AI_DIR_R)
      {
         _loc4_._rotation = -90;
      }
   }
   else if(EOBJ_TYPE == EOBJTYPE_TREKDOOR)
   {
      _loc3_._visible = false;
      _loc8_ = tiles.GetTile_I(_loc2_[4],_loc2_[5]);
      _loc4_._x = _loc8_.pos.x;
      _loc4_._y = _loc8_.pos.y;
      if(_loc2_[2] == 1)
      {
         if(_loc2_[8] == 0)
         {
            _loc4_._rotation = 90;
         }
         else
         {
            _loc4_._rotation = -90;
         }
      }
      else if(_loc2_[7] == 0)
      {
         _loc4_._rotation = 0;
      }
      else
      {
         _loc4_._rotation = 180;
      }
   }
   else if(EOBJ_TYPE == EOBJTYPE_TRAPDOOR)
   {
      _loc8_ = tiles.GetTile_I(_loc2_[4],_loc2_[5]);
      _loc10_ = 0;
      _loc9_ = 0;
      _loc4_._x = _loc8_.pos.x;
      _loc4_._y = _loc8_.pos.y;
      if(_loc2_[2] == 1)
      {
         if(_loc2_[8] == 0)
         {
            _loc4_._rotation = 90;
            _loc9_ = 1;
         }
         else
         {
            _loc4_._rotation = -90;
            _loc9_ = -1;
         }
      }
      else if(_loc2_[7] == 0)
      {
         _loc4_._rotation = 0;
         _loc10_ = 1;
      }
      else
      {
         _loc4_._rotation = 180;
         _loc10_ = -1;
      }
      _loc3_.gotoAndStop(20);
      _loc3_._x = _loc2_[0];
      _loc3_._y = _loc2_[1];
      _loc3_._visible = true;
      _loc6_ = _loc3_.createEmptyMovieClip("triggerbuffer",5);
      _loc6_.lineStyle(0,16768477,80);
      _loc6_.moveTo(0,0);
      _loc6_.lineTo(_loc8_.pos.x + _loc10_ * APP_TILE_SCALE - _loc2_[0],_loc8_.pos.y + _loc9_ * APP_TILE_SCALE - _loc2_[1]);
      _loc6_._visible = this.doortrigsvis;
      this.doorrendList.push(_loc6_);
   }
   else if(EOBJ_TYPE == EOBJTYPE_LOCKDOOR)
   {
      _loc8_ = tiles.GetTile_I(_loc2_[4],_loc2_[5]);
      _loc10_ = 0;
      _loc9_ = 0;
      _loc4_._x = _loc8_.pos.x;
      _loc4_._y = _loc8_.pos.y;
      if(_loc2_[2] == 1)
      {
         if(_loc2_[8] == 0)
         {
            _loc4_._rotation = 90;
            _loc9_ = 1;
         }
         else
         {
            _loc4_._rotation = -90;
            _loc9_ = -1;
         }
      }
      else if(_loc2_[7] == 0)
      {
         _loc4_._rotation = 0;
         _loc10_ = 1;
      }
      else
      {
         _loc4_._rotation = 180;
         _loc10_ = -1;
      }
      _loc3_.gotoAndStop(19);
      _loc3_._x = _loc2_[0];
      _loc3_._y = _loc2_[1];
      _loc3_._visible = true;
      _loc6_ = _loc3_.createEmptyMovieClip("triggerbuffer",5);
      _loc6_.lineStyle(0,16768511,80);
      _loc6_.moveTo(0,0);
      _loc6_.lineTo(_loc8_.pos.x + _loc10_ * APP_TILE_SCALE - _loc2_[0],_loc8_.pos.y + _loc9_ * APP_TILE_SCALE - _loc2_[1]);
      _loc6_._visible = this.doortrigsvis;
      this.doorrendList.push(_loc6_);
   }
   else if(EOBJ_TYPE == EOBJTYPE_HOMINGLAUNCHER)
   {
      _loc3_._visible = false;
   }
   else if(EOBJ_TYPE == EOBJTYPE_EXIT)
   {
      _loc3_.gotoAndStop(18);
      _loc3_._x = _loc2_[2];
      _loc3_._y = _loc2_[3];
      _loc3_._visible = true;
      _loc6_ = _loc3_.createEmptyMovieClip("triggerbuffer",5);
      _loc6_.lineStyle(0,16777215,80);
      _loc6_.moveTo(0,0);
      _loc6_.lineTo(_loc2_[0] - _loc2_[2],_loc2_[1] - _loc2_[3]);
      _loc6_._visible = this.doortrigsvis;
      this.doorrendList.push(_loc6_);
   }
   else if(EOBJ_TYPE == EOBJTYPE_MINE)
   {
      _loc3_._visible = false;
   }
};
