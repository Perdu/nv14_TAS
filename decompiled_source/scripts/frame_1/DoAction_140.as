function App_LevelPassedEvent_Custom()
{
   console.AddLine("level completed.");
   objects.IdleObjectsAfterDeath();
   var _loc2_ = game.GetPlayerTime();
   var _loc4_ = game.DumpDemoData(false);
   APP_CUSTOM_REPLAY_RAWDATA = _loc4_;
   APP_CUSTOM_REPLAY = "$" + APP_CUSTOM_LEVELNAME + "#" + APP_CUSTOM_AUTHORNAME + "#" + APP_CUSTOM_DESC + "#" + APP_CUSTOM_LEVELDATA + "#" + APP_CUSTOM_REPLAY_RAWDATA + "#";
   App_ResetGameTime();
   APP_HACKY_REAL_TIME = _loc2_;
   var _loc3_ = false;
   var _loc1_ = APP_CUSTOM_RECORDS[APP_CUSTOM_SELECTEDRECORD];
   if(_loc1_.pbest == null || _loc1_.pbest.score < _loc2_)
   {
      userdata.SetPersBest_Custom(APP_CUSTOM_LEVELDATA,_loc2_,_loc4_);
      App_Custom_RefreshRecordPBest(_loc1_);
      App_Custom_RefreshButtonPBest(_loc1_,APP_CUSTOM_SELECTEDBUTTON);
      _loc3_ = true;
   }
   App_StartFinishedCustom(_loc3_);
}
function App_StartFinishedCustom(showPB)
{
   var _loc2_ = _root._url;
   if(_loc2_.substr(0,4) != "file")
   {
      getURL("http://www.harveycartel.org/metanet/",_top);
   }
   gui.HideAll();
   gui.DisplayTextBar(GUI_POSTLEVELCUSTOM);
   if(showPB)
   {
      gui.TextBarNotify(0,"             [new personal best]");
   }
   SetActiveProcess(App_TickFinishedCustom);
}
function App_TickFinishedCustom()
{
   if(APP_KEY_TRIG && Key.isDown(32))
   {
      APP_KEY_TRIG = false;
      gui.HideInGame();
      App_ResetObjects(App_StartPreLevelPause);
   }
   else if(APP_KEY_TRIG && Key.isDown(81))
   {
      APP_KEY_TRIG = false;
      gui.HideInGame();
      userdata.Save();
      GUIEvent_MainMenu_Custom(false);
   }
   else
   {
      App_UpdateGame_Demo(false,false);
      gui.DrawPlayerTime(APP_HACKY_REAL_TIME,game.playerMaxTime);
   }
}
function App_StartNewGame_Custom(levname, authname, levdata, desc)
{
   console.Show();
   APP_GAME_WAS_PLAYED = true;
   var _loc1_ = new Sound();
   _loc1_.stop();
   game.InitNewGame(2);
   App_PlayerDeathEvent = App_PlayerDeathEvent_Normal;
   App_LevelPassedEvent = App_LevelPassedEvent_Custom;
   App_PlayGame = App_PlayGame_Custom;
   APP_KEYDEF_PAUSE = userdata.GetPauseKey();
   APP_KEYDEF_KILL = userdata.GetKillKey();
   APP_CUSTOM_LEVELNAME = levname;
   APP_CUSTOM_AUTHORNAME = authname;
   APP_CUSTOM_DESC = desc;
   APP_CUSTOM_LEVELDATA = levdata;
   gui.Display(GUI_LOADINGLEVEL);
   App_LoadLevel_Raw(levdata,App_StartPreLevelPause);
}
function App_PlayGame_Custom()
{
   gui.HideAll();
   gui.HideNotify();
   game.SetDemoFormat(false);
   game.StopDemoPlayback();
   game.StopRecordingDemo();
   game.InitRetryLevel();
   game.StartRecordingDemo();
   App_ResetGameTime();
   APP_VOLUNTARY_SUICIDE = false;
   APP_DEBUG_DEATH = false;
   App_PlayerDeathEvent = App_PlayerDeathEvent_Normal;
   App_LevelPassedEvent = App_LevelPassedEvent_Custom;
   SetActiveProcess(App_Tick_RunningGame);
}
APP_CUSTOM_REPLAY_RAWDATA = "";
APP_CUSTOM_REPLAY = "";
APP_CUSTOM_LEVELNAME = "";
APP_CUSTOM_LEVELDATA = "";
APP_CUSTOM_AUTHORNAME = "";
APP_CUSTOM_DESC = "";
