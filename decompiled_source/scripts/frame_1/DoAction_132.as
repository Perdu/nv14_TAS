function StartApp()
{
   _root.onEnterFrame = RunApp;
   Key.addListener(_root);
   APP_KEY_TRIG = false;
   APP_KEY_PRESSED = false;
   APP_t0 = getTimer();
   APP_FPSBOX = gfx.CreateSprite("fpsBox",LAYER_GUI);
   APP_FPSBOX._x = 0;
   APP_FPSBOX._y = 580;
}
function RunApp()
{
   var _loc2_ = APP_t0;
   APP_t0 = getTimer();
   var _loc1_ = APP_t0 - _loc2_;
   APP_FPSBOX.txt = "" + Math.ceil(_loc1_);
   input.Update();
   console.Update();
   if(Key.isDown(APP_BOSS_KEY))
   {
      if(!APP_BOSSDOWN)
      {
         StartBossMode();
         return undefined;
      }
      APP_BOSSDOWN = true;
   }
   else
   {
      APP_BOSSDOWN = false;
   }
   if(APP_BOSSDELAY)
   {
      APP_BOSSDELAY = false;
      App_ResetGameTime();
   }
   TickApp();
}
function StartBossMode()
{
   APP_BOSSDOWN = true;
   var _loc2_ = new Sound();
   _loc2_.stop();
   _root.onEnterFrame = RunBoss;
   gfx.rootbuffer._visible = false;
   APP_BOSS_PROMPT = _root.attachMovie("bossPrompt","bossPrompt",999);
}
function RunBoss()
{
   if(Key.isDown(81))
   {
      fscommand("quit");
   }
   if(Key.isDown(APP_BOSS_KEY))
   {
      if(!APP_BOSSDOWN)
      {
         StopBossMode();
      }
      APP_BOSSDOWN = true;
   }
   else
   {
      APP_BOSSDOWN = false;
   }
}
function StopBossMode()
{
   APP_BOSSDELAY = true;
   _root.onEnterFrame = RunApp;
   gfx.rootbuffer._visible = true;
   APP_BOSS_PROMPT.removeMovieClip();
}
function CloseApp()
{
}
function SetActiveProcess(func)
{
   TickApp = func;
}
function AppBuildModules()
{
   CURRENT_APP_BUILD_STEP = -2;
   SetActiveProcess(AppBuildingModules);
}
function AppBuildingModules()
{
   var _loc2_;
   if(CURRENT_APP_BUILD_STEP == -2)
   {
      console = new ConsoleObject(16,16,600,300);
      CURRENT_APP_BUILD_STEP++;
      console.Clear();
      console.AddLine("Building App Modules:");
      console.StartTab();
      console.AddLine("ConsoleObject built.");
      gui = new NinjaGUI();
      console.AddLine("NinjaGUI built.");
      gui.Display(GUI_LOADINGAPP);
   }
   else if(CURRENT_APP_BUILD_STEP == -1)
   {
      CURRENT_APP_BUILD_STEP++;
      filesys = new NinjaFilesys_Game();
   }
   else if(CURRENT_APP_BUILD_STEP == 0)
   {
      tiles = new TileMap(APP_NUM_GRIDCOLS,APP_NUM_GRIDROWS,APP_TILE_SCALE,APP_TILE_SCALE);
      CURRENT_APP_BUILD_STEP++;
      console.AddLine("TileMap built.");
      console.StartTab();
      console.AddLine("initing TileMapCells.");
   }
   else if(CURRENT_APP_BUILD_STEP == 1)
   {
      console.Append(".");
      if(!tiles.Building())
      {
         console.StopTab();
         CURRENT_APP_BUILD_STEP++;
      }
   }
   else if(CURRENT_APP_BUILD_STEP == 2)
   {
      objects = new ObjectManager();
      CURRENT_APP_BUILD_STEP++;
      console.AddLine("ObjectManager built.");
   }
   else if(CURRENT_APP_BUILD_STEP == 3)
   {
      userdata = new NinjaUserData();
      APP_BOSS_KEY = userdata.GetBossKey();
      CURRENT_APP_BUILD_STEP++;
      console.AddLine("NinjaUserData built.");
   }
   else if(CURRENT_APP_BUILD_STEP == 4)
   {
      game = new NinjaGame();
      CURRENT_APP_BUILD_STEP++;
      console.AddLine("NinjaGame built.");
   }
   else if(CURRENT_APP_BUILD_STEP == 5)
   {
      CURRENT_APP_BUILD_STEP++;
      console.AddLine("NinjaEditor built.");
   }
   else if(CURRENT_APP_BUILD_STEP == 6)
   {
      gamedata = new NinjaData();
      CURRENT_APP_BUILD_STEP++;
      console.AddLine("NinjaData built.");
   }
   else
   {
      onlineclient = new NinjaOnlineClient();
      console.StopTab();
      Init_Hacky_GoldSound();
      _loc2_ = _root._url;
      if(_loc2_.substr(0,4) != "file")
      {
         getURL("http://www.harveycartel.org/metanet/",_top);
      }
      App_LoadMainMenu();
   }
}
_root.onKeyDown = function()
{
   if(!APP_KEY_PRESSED)
   {
      APP_KEY_TRIG = true;
   }
   else
   {
      APP_KEY_TRIG = false;
   }
   APP_KEY_PRESSED = true;
};
_root.onKeyUp = function()
{
   APP_KEY_PRESSED = false;
};
APP_BOSS_KEY = 96;
APP_BOSS_PROMPT = null;
APP_BOSS_PAUSEDTHREAD = null;
APP_BOSSDOWN = false;
APP_BOSSDELAY = false;
