function NinjaGUI()
{
   this.levelnameMC = gfx.CreateSprite("guiLevelNameMC",LAYER_GUI);
   this.levelnameMC._x = 396;
   this.levelnameMC._y = 580;
   this.levelnameMC._visible = false;
   var _loc6_ = gfx.GetNextDepth_Front();
   this.input_txtbox = _root.attachMovie("inputBox","inputBox" + _loc6_,_loc6_);
   this.input_txtbox._x = 450;
   this.input_txtbox._y = 50;
   this.input_txtbox.tabEnabled = false;
   this.input_txtbox.backgroundColor = 16316664;
   this.input_txtbox._visible = false;
   _loc6_ = gfx.GetNextDepth_Front();
   this.input_txtbox2 = _root.attachMovie("inputBox2","inputBox" + _loc6_,_loc6_);
   this.input_txtbox2._x = 450;
   this.input_txtbox2._y = 200;
   this.input_txtbox2.tabEnabled = false;
   this.input_txtbox2.backgroundColor = 16316664;
   this.input_txtbox2._visible = false;
   this.timeMC = gfx.CreateSprite("timeIndicator",LAYER_GUI);
   this.timeMC._x = APP_TILE_SCALE * 2;
   this.timeMC._y = APP_TILE_SCALE;
   this.timeMC.bar._xscale = 0;
   this.timeMC.txtbox._y = -8;
   this.playerDisplayTime = 0;
   this.practiseMC = gfx.CreateSprite("practiseText",LAYER_GUI);
   this.practiseMC._x = APP_TILE_SCALE * 2;
   this.practiseMC._y = 3;
   this.practiseMC.txt = "[ Practise Mode Active ]";
   this.practiseMC._visible = false;
   _loc6_ = gfx.GetNextDepth_Front();
   _root.createTextField("ninjaGUITextField",_loc6_,0,0,545,290);
   this.textmenuMC = _root.ninjaGUITextField;
   this.textmenuMC.multiline = true;
   this.textmenuMC.wordWrap = true;
   this.textmenuMC.selectable = false;
   this.textmenuMC.border = false;
   var _loc5_ = new TextFormat();
   _loc5_.color = 0;
   _loc5_.font = "_typewriter";
   _loc5_.size = 12;
   _loc5_.align = "left";
   this.textmenuMC.setNewTextFormat(_loc5_);
   this.textmenuMC._x = 44;
   this.textmenuMC._y = 300;
   this.menuMC = gfx.CreateSprite("MenuMC",LAYER_GUI);
   this.menuMC._x = 0;
   this.menuMC._y = 0;
   this.menuMC.inity = this.menuMC._y;
   this.menuMC.gotoAndStop("blank");
   this.menuMC._visible = false;
   this.textlineMC = gfx.CreateSprite("guiTextLineMC",LAYER_GUI);
   this.textlineMC._x = 44;
   this.textlineMC._y = 240;
   this.textlineMC._visible = false;
   this.numExtraLines = 0;
   this.textlineList = new Array();
   var _loc4_ = 0;
   var _loc3_;
   while(_loc4_ < 4)
   {
      _loc3_ = gfx.CreateSprite("guiTextLine2MC",LAYER_GUI);
      _loc3_._x = 44;
      _loc3_._y = 540 - _loc4_ * 32;
      _loc3_._visible = false;
      this.textlineList[_loc4_] = _loc3_;
      _loc4_ = _loc4_ + 1;
   }
   this.InitData();
}
NinjaGUI.prototype.SetPlayerTime = function(t)
{
   this.playerDisplayTime = t;
};
NinjaGUI.prototype.ResetPlayerTime = function()
{
   this.playerDisplayTime = 0;
};
NinjaGUI.prototype.FillPlayerTime = function(cur, maxT)
{
   var _loc3_ = cur - this.playerDisplayTime;
   this.playerDisplayTime += 0.05 * _loc3_;
   var _loc2_ = this.playerDisplayTime / (maxT * 2);
   this.timeMC.bar._xscale = Math.min(700,600 * _loc2_);
   this.timeMC.bar.gotoAndStop(Math.max(1,Math.min(101 - Math.floor(100 * _loc2_),101)));
   this.timeMC.txtbox.txt = this.FormatTime(this.playerDisplayTime);
   this.timeMC.txtbox._x = Math.floor(this.timeMC.bar._xscale) + 1;
};
NinjaGUI.prototype.DrawPlayerTime = function(cur, maxT)
{
   var _loc4_ = cur / maxT;
   var _loc2_ = 1 - _loc4_;
   _loc2_ = Math.min(1,Math.max(0.05,_loc2_ * _loc2_));
   var _loc5_ = cur - this.playerDisplayTime;
   this.playerDisplayTime += _loc2_ * _loc5_;
   var _loc3_ = this.playerDisplayTime / (maxT * 2);
   this.timeMC.bar._xscale = Math.min(700,600 * _loc3_);
   this.timeMC.bar.gotoAndStop(Math.max(1,Math.min(101 - Math.floor(100 * _loc3_),101)));
   this.timeMC.txtbox.txt = this.FormatTime(this.playerDisplayTime);
   this.timeMC.txtbox._x = Math.floor(this.timeMC.bar._xscale) + 1;
};
NinjaGUI.prototype.FormatTime = function(ticks)
{
   var _loc1_ = ticks * APP_GAMETIME_BASETICKLEN;
   var _loc3_ = Math.floor(_loc1_ / 1000);
   _loc1_ = Math.floor(_loc1_ - _loc3_ * 1000);
   var _loc2_ = "";
   if(_loc1_ < 100)
   {
      _loc2_ += "0";
      if(_loc1_ < 10)
      {
         _loc2_ += "0";
      }
   }
   var _loc4_ = "" + _loc3_ + "." + _loc2_ + _loc1_;
   return _loc4_;
};
NinjaGui.prototype.DrawLevelName = function(str)
{
   this.levelnameMC._visible = true;
   this.levelnameMC.txt = str;
};
NinjaGui.prototype.ShowInGame = function()
{
   this.levelnameMC._visible = true;
   this.timeMC._visible = true;
   this.practiseMC._visible = false;
};
NinjaGui.prototype.ShowInGame_Practise = function()
{
   this.levelnameMC._visible = true;
   this.timeMC._visible = false;
   this.practiseMC._visible = true;
};
NinjaGui.prototype.HideInGame = function()
{
   this.playerDisplayTime = 0;
   var _loc3_ = 0;
   this.timeMC.bar._xscale = Math.min(700,600 * _loc3_);
   this.timeMC.bar.gotoAndStop(Math.max(1,Math.min(101 - Math.floor(100 * _loc3_),101)));
   this.timeMC.txtbox.txt = this.FormatTime(0);
   this.timeMC.txtbox._x = Math.floor(this.timeMC.bar._xscale) + 1;
   this.levelnameMC._visible = false;
   this.timeMC._visible = false;
   this.practiseMC._visible = false;
   this.numExtraLines = 0;
   var _loc2_ = 0;
   while(_loc2_ < this.textlineList.length)
   {
      this.textlineList[_loc2_]._visible = false;
      _loc2_ = _loc2_ + 1;
   }
};
NinjaGUI.prototype.HideAll = function()
{
   this.menuMC._visible = false;
   this.textmenuMC._visible = false;
   this.textlineMC._visible = false;
   this.HideTxt();
};
NinjaGUI.prototype.ShowAll = function()
{
   this.menuMC._visible = true;
   this.textmenuMC._visible = true;
   this.textlineMC._visible = true;
};
NinjaGUI.prototype.HideMenu = function()
{
   this.menuMC._visible = false;
};
NinjaGUI.prototype.ShowMenu = function()
{
   this.menuMC._visible = true;
};
NinjaGUI.prototype.HideTextMenu = function()
{
   this.textmenuMC._visible = false;
   this.textlineMC._visible = false;
};
NinjaGUI.prototype.ShowTextMenu = function()
{
   this.textmenuMC._visible = true;
   this.textlineMC._visible = true;
};
NinjaGUI.prototype.DisplayRawText = function(str)
{
   this.textmenuMC._visible = true;
   this.textmenuMC.text = str;
};
NinjaGUI.prototype.DisplayTextBar = function(GUI_ID)
{
   this.textlineMC._visible = true;
   this.textlineMC.txt = this.guiList[GUI_ID];
};
NinjaGUI.prototype.AppendToTextBar = function(str)
{
   this.textlineMC.txt += str;
};
NinjaGUI.prototype.HideNotify = function()
{
   this.numExtraLines = 0;
   var _loc2_ = 0;
   while(_loc2_ < this.textlineList.length)
   {
      this.textlineList[_loc2_]._visible = false;
      _loc2_ = _loc2_ + 1;
   }
};
NinjaGUI.prototype.TextBarNotify = function(num, str)
{
   this.textlineList[num]._visible = true;
   this.textlineList[num].txt = str;
};
NinjaGUI.prototype.Display = function(GUI_ID)
{
   if(this.guiList[GUI_ID] == null)
   {
      return undefined;
   }
   var _loc5_;
   var _loc3_;
   var _loc4_;
   if(GUI_LAST_STRING_INDEX < GUI_ID)
   {
      _loc5_ = this.guiList[GUI_ID];
      this.DisplayFrame(_loc5_);
   }
   else
   {
      _loc3_ = this.guiList[GUI_ID];
      _loc4_ = typeof _loc3_;
      if(_loc4_ == "string")
      {
         this.DisplayString(_loc3_);
      }
      else
      {
         this.DisplayList(_loc3_);
      }
   }
};
NinjaGUI.prototype.GetCurrentMC = function()
{
   return this.menuMC;
};
NinjaGUI.prototype.DisplayFrame = function(frm)
{
   this.textmenuMC._visible = false;
   this.textlineMC._visible = false;
   this.menuMC._visible = true;
   this.menuMC.gotoAndStop(frm);
};
NinjaGUI.prototype.DisplayString = function(str)
{
   this.menuMC._visible = false;
   this.textmenuMC._visible = false;
   this.textlineMC._visible = true;
   this.textlineMC.txt = str;
};
NinjaGUI.prototype.DisplayList = function(strList)
{
   this.menuMC._visible = false;
   this.textlineMC._visible = false;
   this.textmenuMC._visible = true;
   this.textmenuMC.text = "";
   var _loc2_ = 0;
   while(_loc2_ < strList.length)
   {
      this.textmenuMC.text += strList[_loc2_];
      this.textmenuMC.text += "\n";
      _loc2_ = _loc2_ + 1;
   }
};
TXTBOX_TOP = 0;
TXTBOX_BOTTOM = 1;
NinjaGUI.prototype.GetTxt = function(boxNum)
{
   this.ShowTxt();
   if(boxNum == TXTBOX_TOP)
   {
      return this.input_txtbox.txt;
   }
   if(boxNum == TXTBOX_BOTTOM)
   {
      return this.input_txtbox2.txt;
   }
};
NinjaGUI.prototype.SetTxt = function(boxNum, str)
{
   this.ShowTxt();
   if(boxNum == TXTBOX_TOP)
   {
      this.input_txtbox.txt = str;
   }
   else if(boxNum == TXTBOX_BOTTOM)
   {
      this.input_txtbox2.txt = str;
   }
};
NinjaGUI.prototype.HideTxt = function()
{
   this.input_txtbox._visible = this.input_txtbox2._visible = false;
};
NinjaGUI.prototype.ShowTxt = function()
{
   this.input_txtbox._visible = this.input_txtbox2._visible = true;
};
