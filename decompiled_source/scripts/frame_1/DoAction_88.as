function NinjaGame()
{
   this.SetDemoFormat(true);
   this.KEYDEF_L = userdata.GetLeftKey();
   this.KEYDEF_R = userdata.GetRightKey();
   this.KEYDEF_J = userdata.GetJumpKey();
   this.playerMaxTime = 3600;
   this.playerCurTime = 3600;
   this.playerStartingTime = 3600;
   this.playerBonusTime = 80;
   this.isTimeTrial = false;
   this.RECORDING_DEMO = false;
   this.mapStr = "";
   this.objStr = "";
   this.tickCounter = 0;
   this.demoTickCount = 0;
   this.GetInputState = this.GetInputState_Normal;
   var _loc3_ = _root._url;
   if(_loc3_.substr(0,4) != "file")
   {
      getURL("http://www.harveycartel.org/metanet/",_top);
   }
}
NinjaGame.prototype.SetDemoFormat = function(isCompressed)
{
   if(isCompressed)
   {
      this.InstallCompressedCodec();
   }
   else
   {
      this.InstallComplexCodec();
   }
};
NinjaGame.prototype.LoadDemo = function(str)
{
   if(str.charAt(0) == "A")
   {
      this.SetDemoFormat(true);
      this.LoadDemo_Compressed(str);
   }
   else
   {
      this.SetDemoFormat(false);
      this.LoadDemo_Complex(str);
   }
};
NinjaGame.prototype.DumpDemoData = function(isCompressed)
{
   if(isCompressed)
   {
      this.SetDemoFormat(true);
      return this.DumpDemoData_Compressed();
   }
   this.SetDemoFormat(false);
   return this.DumpDemoData_Complex();
};
NinjaGame.prototype.SetKeyDefs = function(jdef, ldef, rdef)
{
   this.KEYDEF_L = ldef;
   this.KEYDEF_R = rdef;
   this.KEYDEF_J = jdef;
};
NinjaGame.prototype.InitNewGame = function(gamemode)
{
   if(gamemode == 2)
   {
      this.isTimeTrial = false;
      this.isCustom = true;
   }
   else if(gamemode == 1)
   {
      this.isTimeTrial = true;
      this.isCustom = false;
   }
   else if(gamemode == 0)
   {
      this.isTimeTrial = false;
      this.isCustom = false;
   }
   this.playerCurTime = this.playerStartingTime = this.playerMaxTime;
   this.tickCounter = 0;
};
NinjaGame.prototype.InitNewLevel = function()
{
   if(this.isTimeTrial)
   {
      this.playerStartingTime = this.playerMaxTime;
   }
   else if(this.isCustom)
   {
      this.playerStartingTime = this.playerMaxTime;
   }
   else
   {
      this.playerStartingTime = this.playerCurTime;
   }
   this.tickCounter = 0;
};
NinjaGame.prototype.InitRetryLevel = function()
{
   this.playerCurTime = this.playerStartingTime;
   this.tickCounter = 0;
};
NinjaGame.prototype.Tick = function()
{
   debug_rend.Clear();
   static_rend.Clear();
   objects.Tick();
   player.Tick();
   this.tickCounter = this.tickCounter + 1;
};
NinjaGame.prototype.Draw = function()
{
   objects.Draw();
};
NinjaGame.prototype.DrawPlayerTime = function()
{
   gui.DrawPlayerTime(this.playerCurTime,this.playerMaxTime);
};
NinjaGame.prototype.FillPlayerTime = function()
{
   gui.FillPlayerTime(this.playerCurTime,this.playerMaxTime);
};
NinjaGame.prototype.GetPlayerTime = function()
{
   return this.playerCurTime;
};
NinjaGame.prototype.GetPlayerLevelTime = function()
{
   var _loc2_ = this.playerMaxTime + (this.playerCurTime - this.playerStartingTime);
   return _loc2_;
};
NinjaGame.prototype.GetTime = function()
{
   return this.tickCounter;
};
NinjaGame.prototype.GiveBonusTime = function()
{
   this.playerCurTime += this.playerBonusTime;
};
KILLTYPE_ELECTRIC = 0;
KILLTYPE_EXPLOSIVE = 1;
KILLTYPE_WEAKBULLET = 2;
KILLTYPE_HARDBULLET = 3;
KILLTYPE_FALL = 4;
KILLTYPE_LASER = 5;
NinjaGame.prototype.KillPlayer = function(killtype, fx, fy, px, py, obj)
{
   var _loc1_;
   var _loc3_;
   if(!player.isDead)
   {
      player.Die(fx,fy,px,py,killtype);
      if(killtype == KILLTYPE_EXPLOSIVE)
      {
         player.raggy.Explode();
      }
      App_PlayerDeathEvent();
      _loc1_ = "You were killed by ";
      _loc3_ = objects.GetObjType(obj);
      if(_loc3_ == OBJTYPE_PLAYER)
      {
         _loc1_ += "yourself!! looooooser!!";
         if(!APP_DEBUG_DEATH)
         {
            userdata.IncrementKillCount("player");
         }
      }
      else
      {
         _loc1_ += "a " + obj.name;
         if(!APP_DEBUG_DEATH)
         {
            userdata.IncrementKillCount(obj.name);
         }
      }
      console.AddLine(_loc1_);
   }
};
