function App_StartNewGame_Debug()
{
   game.InitNewGame();
   APP_DEBUG_DEATH = true;
   App_LoadDebugMenu();
}
function App_LoadDebugMenu()
{
   _root.editor = new NinjaEditor();
   editor.Init();
   App_StartDebugMenu();
}
function App_KillDebugMenu()
{
   editor.Destroy();
}
function App_StartDebugMenu()
{
   App_PlayerDeathEvent = App_PlayerDeathEvent_Debug;
   App_LevelPassedEvent = App_LevelPassedEvent_Debug;
   gui.Display(GUI_DEBUGMENU);
   console.Show();
   gui.ShowTxt();
   gui.SetTxt(TXTBOX_TOP,game.DumpLevelData());
   gui.SetTxt(TXTBOX_BOTTOM,game.DumpDemoData(false));
   APP_DEBUG_MODE_ACTIVE = true;
   APP_DEBUG_DEATH = true;
   SetActiveProcess(App_Tick_DebugMenu);
}
function App_Tick_DebugMenu()
{
   var _loc1_;
   if(APP_KEY_TRIG && Key.isDown(49))
   {
      APP_KEY_TRIG = false;
      game.StopRecordingDemo();
      game.InitNewGame();
      game.StartRecordingDemo();
   }
   else if(APP_KEY_TRIG && Key.isDown(50))
   {
      APP_KEY_TRIG = false;
      game.StopRecordingDemo();
   }
   else if(APP_KEY_TRIG && Key.isDown(87))
   {
      APP_KEY_TRIG = false;
      game.StopDemoPlayback();
   }
   else if(APP_KEY_TRIG && Key.isDown(81))
   {
      APP_KEY_TRIG = false;
      game.InitNewGame();
      App_ResetObjects(App_StartDemoPlayback_Debug);
   }
   else if(APP_KEY_TRIG && Key.isDown(51))
   {
      APP_KEY_TRIG = false;
      _loc1_ = gui.GetTxt(TXTBOX_BOTTOM);
      game.LoadDemo(_loc1_);
   }
   else if(APP_KEY_TRIG && Key.isDown(52))
   {
      APP_KEY_TRIG = false;
      _loc1_ = game.DumpDemoData(false);
      System.setClipboard(_loc1_);
      gui.ShowTxt();
      gui.SetTxt(TXTBOX_BOTTOM,_loc1_);
   }
   if(APP_KEY_TRIG && Key.isDown(77))
   {
      APP_KEY_TRIG = false;
      gui.HideTxt();
      App_KillDebugMenu();
      App_LoadMainMenu();
   }
   else if(APP_KEY_TRIG && Key.isDown(74))
   {
      APP_KEY_TRIG = false;
      App_LoadLevel_Raw(gamedata.GetBlankMap(),App_StartDebugMenu);
   }
   else if(APP_KEY_TRIG && Key.isDown(72))
   {
      APP_KEY_TRIG = false;
      App_LoadLevel_Raw(gamedata.GetFullMap(),App_StartDebugMenu);
   }
   else if(APP_KEY_TRIG && Key.isDown(80))
   {
      APP_KEY_TRIG = false;
      gui.HideTxt();
      console.Hide();
      App_PlayGame_Debug();
   }
   else if(APP_KEY_TRIG && Key.isDown(69))
   {
      APP_KEY_TRIG = false;
      gui.HideTxt();
      console.Hide();
      App_StartEditor();
   }
   else if(APP_KEY_TRIG && Key.isDown(82))
   {
      APP_KEY_TRIG = false;
      App_ResetObjects(App_StartDebugMenu);
   }
   else if(APP_KEY_TRIG && Key.isDown(84))
   {
      APP_KEY_TRIG = false;
      gui.HideTxt();
      console.Hide();
      App_ResetObjects(App_StartEditor);
   }
   else if(APP_KEY_TRIG && Key.isDown(76))
   {
      APP_KEY_TRIG = false;
      _loc1_ = gui.GetTxt(TXTBOX_TOP);
      App_LoadLevel_Raw(_loc1_,App_StartDebugMenu);
   }
   else if(APP_KEY_TRIG && Key.isDown(83))
   {
      APP_KEY_TRIG = false;
      _loc1_ = game.DumpLevelData();
      System.setClipboard(_loc1_);
      gui.ShowTxt();
      gui.SetTxt(TXTBOX_TOP,_loc1_);
   }
}
function App_StartDemoPlayback_Debug()
{
   game.InitNewGame();
   game.StartDemoPlayback();
   App_StartDebugMenu();
}
function App_PlayGame_Debug()
{
   gui.HideAll();
   App_ResetGameTime();
   SetActiveProcess(App_Tick_RunningGame_Debug);
}
function App_Tick_RunningGame_Debug()
{
   if(Key.isDown(192) || Key.isDown(220))
   {
      APP_KEY_TRIG = false;
      App_StartDebugMenu();
      return undefined;
   }
   if(Key.isToggled(20))
   {
      if(!APP_DID_TICK_DEBUG)
      {
         App_ResetGameTime();
      }
      DebugUpdateGameCode();
      App_UpdateGame();
      APP_DID_TICK_DEBUG = true;
   }
   else if(input.MousePressed())
   {
      static_rend.Clear();
      if(Key.isDown(8))
      {
         player.raggy.Activate();
         player.raggy.MimicMC(0,0,player.mc,player.facingDir,player.prevframe);
         player.mc._visible = false;
         player.raggy.Draw();
      }
      if(Key.isDown(45))
      {
         player.raggy.Deactivate();
         player.mc._visible = true;
      }
      App_ResetGameTime();
      APP_GAMETIME_REMAINDER = APP_GAMETIME_TICKLEN + 1;
      DebugUpdateGameCode();
      App_UpdateGame();
      APP_DID_TICK_DEBUG = true;
   }
   else
   {
      APP_DID_TICK_DEBUG = false;
   }
}
function App_StartEditor()
{
   gui.Display(GUI_TEMP_EDITOR);
   SetActiveProcess(App_TickEditor);
   editor.Start();
}
function App_TickEditor()
{
   App_UpdateEditor();
}
function App_UpdateEditor()
{
   debug_rend.Clear();
   static_rend.Clear();
   editor.Tick();
}
APP_DEBUG_MODE_ACTIVE = true;
APP_DID_TICK_DEBUG = false;
