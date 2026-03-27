function App_LoadMainMenu()
{
   var _loc3_ = _root._url;
   if(_loc3_.substr(0,4) != "file")
   {
      getURL("http://www.harveycartel.org/metanet/",_top);
   }
   var _loc2_ = new Sound();
   _loc2_.stop();
   _loc2_.setVolume(Math.round(userdata.GetVol()));
   APP_DEBUG_MODE_ACTIVE = false;
   App_StartLoadingMenuDemo();
   App_StartMainMenu();
}
function App_StartMainMenu()
{
   if(APP_GAME_WAS_PLAYED)
   {
      APP_GAME_WAS_PLAYED = false;
      App_LoadMainMenu();
   }
   var _loc3_ = _root._url;
   if(_loc3_.substr(0,4) != "file")
   {
      getURL("http://www.harveycartel.org/metanet/",_top);
   }
   APP_DEBUG_MODE_ACTIVE = false;
   var _loc2_ = new Sound();
   _loc2_.stop();
   _loc2_.setVolume(Math.round(userdata.GetVol()));
   APP_PRE_QUIT = false;
   App_PlayerDeathEvent = App_PlayerDeathEvent_Normal;
   App_LevelPassedEvent = App_PlayerDeathEvent_Normal;
   gui.HideInGame();
   gui.Display(GUI_MAINMENU);
   App_ResetGameTime();
   SetActiveProcess(App_Tick_MainMenu);
}
function GUIEvent_MainMenu_Help()
{
   console.Show();
   game.StopDemoPlayback();
   var _loc1_ = new Sound();
   _loc1_.stop();
   App_ResetGameTime();
   App_StartHelp();
}
function GUIEvent_MainMenu_Story()
{
   console.Hide();
   App_ResetGameTime();
   gui.Display(GUI_STORY);
}
function GUIEvent_MainMenu_Quit()
{
   console.Hide();
   App_ResetGameTime();
   App_StartQuit();
}
function GUIEvent_MainMenu_Credits()
{
   console.Hide();
   App_ResetGameTime();
   App_StartCredits();
}
function GUIEvent_MainMenu_PlayGame()
{
   App_ResetGameTime();
   App_StartPlayMenu();
}
function GUIEvent_MainMenu_Custom(reload)
{
   console.Hide();
   App_ResetGameTime();
   App_StartCustomMenu(reload);
}
function GUIEvent_MainMenu_Configure()
{
   App_ResetGameTime();
   App_StartConfigMenu();
}
function GUIEvent_MainMenu_ContinueGame()
{
   App_ResetGameTime();
   App_StartContinue();
}
function GUIEvent_MainMenu_Highscores()
{
   console.Hide();
   App_ResetGameTime();
   App_StartHighscoreMenu(true);
}
function GUIEvent_MainMenu_TimeTrial(newDemo)
{
   console.Hide();
   App_ResetGameTime();
   App_StartHighscoreMenu(false);
}
function GUIEvent_MainMenu_Editor()
{
   game.StopDemoPlayback();
   App_StartNewGame_Debug();
}
function App_Tick_MainMenu()
{
   if(APP_PRE_QUIT)
   {
      if(APP_KEY_TRIG && Key.isDown(89))
      {
         APP_KEY_TRIG = false;
         App_Quit();
         return undefined;
      }
      if(APP_KEY_TRIG && Key.isDown(78))
      {
         APP_KEY_TRIG = false;
         App_StartMainMenu();
      }
   }
   else
   {
      if(APP_KEY_TRIG && Key.isDown(72))
      {
         APP_KEY_TRIG = false;
         GUIEvent_MainMenu_Help();
         return undefined;
      }
      if(APP_KEY_TRIG && Key.isDown(83))
      {
         APP_KEY_TRIG = false;
         GUIEvent_MainMenu_Story();
         return undefined;
      }
      if(APP_KEY_TRIG && Key.isDown(81))
      {
         APP_KEY_TRIG = false;
         GUIEvent_MainMenu_Quit();
         return undefined;
      }
      if(APP_KEY_TRIG && Key.isDown(78))
      {
         APP_KEY_TRIG = false;
         GUIEvent_MainMenu_PlayGame();
         return undefined;
      }
      if(APP_KEY_TRIG && Key.isDown(67))
      {
         APP_KEY_TRIG = false;
         GUIEvent_MainMenu_Configure();
         return undefined;
      }
      if(APP_KEY_TRIG && Key.isDown(192) || APP_KEY_TRIG && Key.isDown(220))
      {
         APP_KEY_TRIG = false;
         GUIEvent_MainMenu_Editor();
         return undefined;
      }
      if(APP_KEY_TRIG && Key.isDown(101))
      {
         APP_KEY_TRIG = false;
         GUIEvent_MainMenu_ContinueGame();
         return undefined;
      }
      if(APP_KEY_TRIG && Key.isDown(108))
      {
         APP_KEY_TRIG = false;
         GUIEvent_MainMenu_Credits();
         return undefined;
      }
      if(APP_KEY_TRIG && Key.isDown(89))
      {
         APP_KEY_TRIG = false;
         GUIEvent_MainMenu_Highscores();
         return undefined;
      }
      if(APP_KEY_TRIG && Key.isDown(85))
      {
         APP_KEY_TRIG = false;
         GUIEvent_MainMenu_Custom(true);
         return undefined;
      }
   }
   App_UpdateMainMenu();
}
function App_StartLoadingMenuDemo()
{
   App_PlayerDeathEvent = App_PlayerDeathEvent_Normal;
   App_LevelPassedEvent = App_PlayerDeathEvent_Normal;
   App_UpdateMainMenu = App_UpdateMainMenu_LoadDemo;
   game.StopDemoPlayback();
   game.InitNewGame(false);
   var _loc1_ = gamedata.GetCurrentMenuDemoID();
   App_LoadMenuDemo(_loc1_);
   APP_DEBUG_DEATH = true;
   gamedata.IncrementCurrentMenuDemo();
   console.Show();
}
function App_UpdateMainMenu_LoadDemo()
{
   if(!App_LoadingMenuDemo())
   {
      APP_DEBUG_DEATH = true;
      console.Hide();
      game.InitNewLevel();
      game.StartDemoPlayback();
      App_UpdateMainMenu = App_UpdateMainMenu_TickDemo;
      App_ResetGameTime();
   }
}
function App_UpdateMainMenu_TickDemo()
{
   var _loc1_ = game.GetDemoTickCount() - game.GetTime();
   var _loc2_;
   if(_loc1_ < -130 || player.isDead && 130 < game.GetTime() - player.timeOfDeath)
   {
      _loc2_ = new Sound();
      _loc2_.stop();
      App_StartLoadingMenuDemo();
      return undefined;
   }
   App_UpdateGame_Demo(false,false);
}
function App_StartContinue()
{
   gui.Display(GUI_CONTINUE);
   SetActiveProcess(App_TickContinue);
}
function App_TickContinue()
{
   App_UpdateMainMenu();
}
function App_ReadInputContinueCode()
{
   var _loc2_ = gui.GetCurrentMC().continuemenu;
   var _loc1_ = _loc2_.txt;
   App_SubmitContinueCode(_loc1_);
}
function App_SubmitContinueCode(code)
{
   var _loc1_;
   if(code != "xxxx" && gamedata.LoadEpisode(code))
   {
      _loc1_ = new Sound();
      _loc1_.stop();
      userdata.NotifyEpisodeReached(gamedata.curEpisode);
      APP_IS_CHEATER = true;
      App_StartNewGame();
   }
   else
   {
      gamedata.ResetEpisode();
      console.AddLine("Invalid Episode Code.");
      App_StartMainMenu();
   }
}
function App_StartCredits()
{
   var _loc1_ = Math.random();
   if(_loc1_ < 0.14285714285714285)
   {
      gui.Display(GUI_GOODBYE4);
   }
   else if(_loc1_ < 0.2857142857142857)
   {
      gui.Display(GUI_GOODBYE3);
   }
   else if(_loc1_ < 0.42857142857142855)
   {
      gui.Display(GUI_GOODBYE2);
   }
   else if(_loc1_ < 0.5714285714285714)
   {
      gui.Display(GUI_GOODBYE1);
   }
   else if(_loc1_ < 0.7142857142857143)
   {
      gui.Display(GUI_GOODBYE5);
   }
   else if(_loc1_ < 0.8571428571428571)
   {
      gui.Display(GUI_GOODBYE6);
   }
   else
   {
      gui.Display(GUI_GOODBYE7);
   }
   APP_KEY_TRIG = false;
   SetActiveProcess(App_TickCredits);
}
function App_TickCredits()
{
   if(APP_KEY_TRIG)
   {
      APP_KEY_TRIG = false;
      App_ResetGameTime();
      App_StartMainMenu();
   }
}
function App_StartHelp()
{
   gui.Display(GUI_HELP);
   2;
   var _loc1_ = gui.GetCurrentMC().helpmenu;
   _loc1_.keyL._visible = false;
   _loc1_.keyR._visible = false;
   _loc1_.keyJ._visible = false;
   APP_DEBUG_DEATH = true;
   SetActiveProcess(App_Tick_Help);
   App_UpdateHelp = App_UpdateHelp_LoadLevel;
   APP_HELPLEVEL_LOADED = false;
   App_BeginLoadMenuDemo(gamedata.GetHelpLevelData(),"");
}
function App_UpdateHelp_LoadLevel()
{
   if(!App_LoadingMenuDemo())
   {
      APP_HELPLEVEL_LOADED = true;
      App_StartHelpDemo(HELPDEMO_WELCOME);
   }
}
function App_StartHelpDemo(demoID)
{
   var _loc1_;
   if(APP_HELPLEVEL_LOADED)
   {
      _loc1_ = new Sound();
      _loc1_.stop();
      console.Show();
      App_LoadHelpDemo(demoID);
      App_UpdateHelp = App_UpdateHelp_LoadDemo;
   }
}
function App_ContinueHelpDemo()
{
   console.Show();
   var _loc1_ = new Sound();
   _loc1_.stop();
   App_ResetHelpDemo();
   App_UpdateHelp = App_UpdateHelp_ResetDemo;
}
function App_PlayHelpDemo(str)
{
   var _loc2_ = new Sound();
   _loc2_.stop();
   App_PlayerDeathEvent = App_PlayerDeathEvent_Normal;
   App_LevelPassedEvent = App_PlayerDeathEvent_Normal;
   game.InitNewGame(false);
   App_ResetGameTime();
   gui.ResetPlayerTime();
   game.StopDemoPlayback();
   game.LoadDemo(str);
   game.StartDemoPlayback();
   App_UpdateHelp = App_UpdateHelp_TickDemo;
   var _loc1_ = gui.GetCurrentMC().helpmenu;
   _loc1_.keyL._visible = true;
   _loc1_.keyR._visible = true;
   _loc1_.keyJ._visible = true;
   _loc1_.keyL.gotoAndStop(2);
   _loc1_.keyR.gotoAndStop(2);
   _loc1_.keyJ.gotoAndStop(2);
}
function App_Tick_Help()
{
   if(Key.isDown(49))
   {
      App_StartHelpDemo(HELPDEMO_JUMP1);
   }
   else if(Key.isDown(50))
   {
      App_StartHelpDemo(HELPDEMO_JUMP2);
   }
   else if(Key.isDown(51))
   {
      App_StartHelpDemo(HELPDEMO_MOVE1);
   }
   if(APP_KEY_TRIG && Key.isDown(77))
   {
      APP_KEY_TRIG = false;
      App_LoadMainMenu();
   }
   else
   {
      App_UpdateHelp();
   }
}
function App_UpdateHelp_LoadDemo()
{
   if(!App_LoadingHelpDemo())
   {
      console.Hide();
      App_PlayHelpDemo(gamedata.GetCurrentHelpDemoData());
   }
}
function App_UpdateHelp_ResetDemo()
{
   if(!App_ResettingHelpDemo())
   {
      console.Hide();
      App_PlayHelpDemo(gamedata.GetCurrentHelpDemoData());
   }
}
function App_UpdateHelp_TickDemo()
{
   if(game.GetDemoTickCount() - game.GetTime() < -60)
   {
      gamedata.IncrementHelpDemoReel();
      App_ContinueHelpDemo();
      return undefined;
   }
   App_UpdateGame_Demo(false,false);
   var _loc1_ = gui.GetCurrentMC().helpmenu;
   var _loc2_ = player.inputList;
   if(_loc2_[PINPUT_R])
   {
      _loc1_.keyR.gotoAndStop(1);
   }
   else
   {
      _loc1_.keyR.gotoAndStop(2);
   }
   if(_loc2_[PINPUT_L])
   {
      _loc1_.keyL.gotoAndStop(1);
   }
   else
   {
      _loc1_.keyL.gotoAndStop(2);
   }
   if(_loc2_[PINPUT_J])
   {
      _loc1_.keyJ.gotoAndStop(1);
   }
   else
   {
      _loc1_.keyJ.gotoAndStop(2);
   }
}
function App_StartQuit()
{
   gui.Display(GUI_CONFIRMQUIT);
   APP_PRE_QUIT = true;
}
function App_Quit()
{
   var _loc2_ = new Sound();
   _loc2_.stop();
   var _loc1_ = Math.random();
   if(_loc1_ < 0.14285714285714285)
   {
      gui.Display(GUI_GOODBYE4);
   }
   else if(_loc1_ < 0.2857142857142857)
   {
      gui.Display(GUI_GOODBYE3);
   }
   else if(_loc1_ < 0.42857142857142855)
   {
      gui.Display(GUI_GOODBYE2);
   }
   else if(_loc1_ < 0.5714285714285714)
   {
      gui.Display(GUI_GOODBYE1);
   }
   else if(_loc1_ < 0.7142857142857143)
   {
      gui.Display(GUI_GOODBYE5);
   }
   else if(_loc1_ < 0.8571428571428571)
   {
      gui.Display(GUI_GOODBYE6);
   }
   else
   {
      gui.Display(GUI_GOODBYE7);
   }
   console.mc._visible = false;
   SetActiveProcess(App_TickGoodbye);
}
function App_TickGoodbye()
{
   if(APP_KEY_TRIG)
   {
      SetActiveProcess(App_Cleanup);
   }
}
function App_Cleanup()
{
   CloseApp();
   fscommand("quit");
}
