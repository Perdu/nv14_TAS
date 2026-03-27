function App_LoadHelpDemo(demoID)
{
   gamedata.SetCurrentHelpDemo(demoID);
   var _loc1_ = gamedata.GetHelpDemoObjects();
   if(_loc1_ != null)
   {
      App_BeginLoadHelpDemo(_loc1_);
   }
}
function App_BeginLoadHelpDemo(objStr)
{
   console.AddLine("Loading Objects");
   console.AddLine(".");
   game.InitLoadObjects(objStr);
}
function App_LoadingHelpDemo()
{
   if(!AppLoadingObjects())
   {
      return false;
   }
   return true;
}
function App_ResetHelpDemo()
{
   console.AddLine("Resetting Objects");
   console.AddLine(".");
   game.InitReloadObjects();
}
function App_ResettingHelpDemo()
{
   if(!AppLoadingObjects())
   {
      return false;
   }
   return true;
}
function App_LoadMenuDemo(demoID)
{
   var _loc1_ = gamedata.GetMenuDemoData(demoID);
   game.LoadDemo(_loc1_);
   var _loc2_ = gamedata.GetMenuDemoLevel(demoID);
   if(_loc2_ != null)
   {
      App_BeginLoadMenuDemo(_loc2_,_loc1_);
      return true;
   }
   return false;
}
function App_BeginLoadMenuDemo(levStr, demStr)
{
   console.AddLine("Loading Level:");
   console.StartTab();
   console.AddLine("Loading Map");
   console.AddLine(".");
   APP_DONE_LOADING_MAP = false;
   game.InitLoadLevel(levStr);
}
function App_LoadingMenuDemo()
{
   if(!APP_DONE_LOADING_MAP)
   {
      if(!AppLoadingMap())
      {
         console.AddLine("Loading Objects");
         console.AddLine(".");
         APP_DONE_LOADING_MAP = true;
      }
   }
   else if(!AppLoadingObjects())
   {
      console.StopTab();
      return false;
   }
   return true;
}
function App_LoadLevel(levelID, callback)
{
   var _loc1_ = gamedata.GetLevelData(levelID);
   if(_loc1_ != null)
   {
      App_BeginLoadLevel(_loc1_,callback);
   }
}
function App_LoadLevel_Raw(str, callback)
{
   gui.Display(GUI_LOADINGLEVEL);
   var _loc1_ = "";
   var _loc2_;
   if(str.substr(0,1) == "$")
   {
      _loc2_ = str.split("#");
      _loc1_ = _loc2_[3];
   }
   else
   {
      _loc1_ = str;
   }
   App_BeginLoadLevel(_loc1_,callback);
}
function App_ResetObjects(callback)
{
   gui.Display(GUI_RESETTINGLEVEL);
   App_BeginResetObjects(callback);
}
function App_BeginLoadLevel(levStr, callback)
{
   LEVEL_LOADED_CALLBACK = callback;
   console.AddLine("Loading Level:");
   console.StartTab();
   console.AddLine("Loading Map");
   console.AddLine(".");
   APP_DONE_LOADING_MAP = false;
   game.InitLoadLevel(levStr);
   SetActiveProcess(AppLoadingLevel);
}
function App_BeginResetObjects(callback)
{
   OBJECTS_LOADED_CALLBACK = callback;
   console.AddLine("Resetting Objects");
   console.AddLine(".");
   game.InitReloadObjects();
   SetActiveProcess(AppResettingObjects);
}
function AppResettingObjects()
{
   if(!AppLoadingObjects())
   {
      OBJECTS_LOADED_CALLBACK();
   }
}
function AppLoadingLevel()
{
   if(!APP_DONE_LOADING_MAP)
   {
      if(!AppLoadingMap())
      {
         console.AddLine("Loading Objects");
         console.AddLine(".");
         APP_DONE_LOADING_MAP = true;
      }
   }
   else if(!AppLoadingObjects())
   {
      console.StopTab();
      LEVEL_LOADED_CALLBACK();
   }
}
function AppLoadingMap()
{
   var _loc1_ = 18;
   while(_loc1_--)
   {
      console.Append(".");
      if(!game.LoadingMap())
      {
         return false;
      }
   }
   console.Update();
   return true;
}
function AppLoadingObjects()
{
   var _loc1_ = 2;
   while(_loc1_--)
   {
      console.Append(".");
      if(!game.LoadingObjects())
      {
         return false;
      }
   }
   console.Update();
   return true;
}
LEVEL_LOADED_CALLBACK = null;
OBJECTS_LOADED_CALLBACK = null;
DEMO_LOADED_CALLBACK = null;
