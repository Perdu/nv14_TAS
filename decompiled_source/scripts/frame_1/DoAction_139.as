function App_PostLevelResponse_NextLevel()
{
   var _loc3_ = _root._url;
   if(_loc3_.substr(0,4) != "file")
   {
      getURL("http://www.harveycartel.org/metanet/",_top);
   }
   APP_VICTORY = false;
   console.Show();
   var _loc2_ = new Sound();
   _loc2_.stop();
   gui.HideInGame();
   SetActiveProcess(null);
   if(!APP_IS_CHEATER && !APP_IS_PRACTISE)
   {
      userdata.NotifyLevelBeaten(gamedata.curEpisode,gamedata.curLevel);
      userdata.NotifyLevelReached(gamedata.curEpisode,gamedata.curLevel);
   }
   else
   {
      userdata.NotifyLevelReached(gamedata.curEpisode,gamedata.curLevel);
   }
   gui.Display(GUI_LOADINGLEVEL);
   App_LoadLevel(gamedata.GetCurrentLevelID(),App_StartPreLevelPause);
}
function App_PostLevelResponse_NextEpisode()
{
   var _loc3_ = _root._url;
   if(_loc3_.substr(0,4) != "file")
   {
      getURL("http://www.harveycartel.org/metanet/",_top);
   }
   APP_KEY_TRIG = false;
   var _loc2_ = gamedata.GetNextEpisodeNum();
   SetActiveProcess(null);
   if(_loc2_ < 0)
   {
      console.AddLine("journey completed.");
      App_StartBeatGame();
   }
   else
   {
      if(!APP_IS_CHEATER && !APP_IS_PRACTISE)
      {
         userdata.NotifyEpisodeBeaten(_loc2_);
         userdata.NotifyEpisodeReached(_loc2_);
      }
      else
      {
         userdata.NotifyEpisodeReached(_loc2_);
      }
      console.AddLine("episode completed. #: " + (_loc2_ - 1));
      App_StartPassedEpisode(_loc2_);
   }
}
function App_PlayerDeathEvent_Normal()
{
   objects.IdleObjectsAfterDeath();
}
function App_PlayerDeathEvent_Debug()
{
}
function App_PlayerDeathEvent_Demo()
{
   objects.IdleObjectsAfterDeath();
}
function App_LevelPassedEvent_Normal()
{
   console.AddLine("level completed.");
   objects.IdleObjectsAfterDeath();
   var _loc2_ = game.GetPlayerTime();
   var _loc3_ = game.GetPlayerLevelTime();
   var _loc5_ = game.DumpDemoData(false);
   App_ResetGameTime();
   var _loc4_ = gamedata.curLevel;
   APP_HACKY_REAL_TIME = _loc2_;
   if(APP_PERSBEST_ACTIVE && !APP_IS_CHEATER && !APP_IS_PRACTISE)
   {
      APP_PERSBEST_EPISBEST = false;
      APP_PERSBEST_LEV = APP_PERSBEST_EP.lev[gamedata.curLevel];
      APP_PERSBEST_PENDINGLEVNUM = gamedata.curLevel;
      if(APP_PERSBEST_LEV.score < _loc3_)
      {
         APP_PERSBEST_EP_PENDING = true;
         userdata.SubmitPersBest_Level(gamedata.curEpisode,gamedata.curLevel,_loc3_);
         App_PersBestEpLevel_DemoReady(_loc5_);
      }
      else
      {
         App_EpisodeLevel_DemoReady(_loc5_);
      }
   }
   var _loc6_ = gamedata.IncrementCurrentLevel();
   if(_loc6_)
   {
      if(APP_ONLINE_ACTIVE && APP_ONLINEGOAL_VALID && APP_ONLINEGOAL_LEVLIST[_loc4_] < _loc3_)
      {
         App_OnlineReplaySent_Level = App_OnlineReplaySent_Level_Active;
         onlineclient.SubmitLevelDemo(gamedata.curEpisode,_loc4_,_loc3_,_loc5_,App_OnlineReplaySent_Level);
         gui.TextBarNotify(2,"[new online highscore]  (uploading replay..)");
      }
      game.InitNewLevel();
      App_StartPostLevelPause(APP_POSTLEVEL_NEXTLEV);
   }
   else
   {
      if(APP_ONLINE_ACTIVE && APP_ONLINEGOAL_VALID && APP_ONLINEGOAL_LEVLIST[_loc4_] < _loc3_)
      {
         if(APP_ONLINE_ACTIVE && APP_ONLINEGOAL_VALID && APP_ONLINEGOAL_EPISODE < _loc2_)
         {
            App_OnlineReplaySent_EpisodeAndLevel = App_OnlineReplaySent_EpisodeAndLevel_Active;
            onlineclient.SubmitEpisodeAndLevelDemo(gamedata.curEpisode,_loc4_,_loc2_,_loc3_,_loc5_,APP_PERSBEST_EPDEMOS[0],APP_PERSBEST_EPDEMOS[1],APP_PERSBEST_EPDEMOS[2],APP_PERSBEST_EPDEMOS[3],APP_PERSBEST_EPDEMOS[4],App_OnlineReplaySent_EpisodeAndLevel);
            gui.TextBarNotify(2,"[new online highscore]  (uploading replay..)");
            gui.TextBarNotify(3,"[new online highscore]  (uploading replay..)");
         }
         else
         {
            App_OnlineReplaySent_Level = App_OnlineReplaySent_Level_Active;
            onlineclient.SubmitLevelDemo(gamedata.curEpisode,_loc4_,_loc3_,_loc5_,App_OnlineReplaySent_Level);
            gui.TextBarNotify(2,"[new online highscore]  (uploading replay..)");
         }
      }
      else if(APP_ONLINE_ACTIVE && APP_ONLINEGOAL_VALID && APP_ONLINEGOAL_EPISODE < _loc2_)
      {
         App_OnlineReplaySent_Episode = App_OnlineReplaySent_Episode_Active;
         onlineclient.SubmitEpisodeDemo(gamedata.curEpisode,_loc2_,APP_PERSBEST_EPDEMOS[0],APP_PERSBEST_EPDEMOS[1],APP_PERSBEST_EPDEMOS[2],APP_PERSBEST_EPDEMOS[3],APP_PERSBEST_EPDEMOS[4],App_OnlineReplaySent_Episode);
         gui.TextBarNotify(3,"[new online highscore]  (uploading replay..)");
      }
      if(APP_PERSBEST_ACTIVE && (!APP_IS_CHEATER && !APP_IS_PRACTISE))
      {
         if(APP_PERSBEST_EP.ep.score < _loc2_)
         {
            userdata.SetPersBest_Episode(gamedata.curEpisode,_loc2_,APP_PERSBEST_EPDEMOS);
            if(APP_PERSBEST_EP_PENDING)
            {
               APP_PERSBEST_EPISBEST = true;
               APP_PERSBEST_EP_TIME = gui.FormatTime(_loc2_);
               APP_PERSBEST_EP_NUM = gamedata.curEpisode;
            }
            else
            {
               gui.TextBarNotify(1,"[new personal best]  Episode " + gamedata.curEpisode);
            }
         }
      }
      App_StartPostLevelPause(APP_POSTLEVEL_NEXTEP);
   }
}
function App_LevelPassedEvent_TimeTrial()
{
   console.AddLine("level completed.");
   objects.IdleObjectsAfterDeath();
   var _loc1_ = game.GetPlayerTime();
   var _loc2_ = game.DumpDemoData(false);
   App_ResetGameTime();
   APP_HACKY_REAL_TIME = _loc1_;
   if(APP_ONLINE_ACTIVE && APP_ONLINEGOAL_VALID && APP_ONLINEGOAL_LEVEL < _loc1_)
   {
      App_OnlineReplaySent_Level = App_OnlineReplaySent_Level_Active;
      onlineclient.SubmitLevelDemo(gamedata.curEpisode,gamedata.curLevel,_loc1_,_loc2_,App_OnlineReplaySent_Level);
      gui.TextBarNotify(2,"[new online highscore]  (uploading replay..)");
   }
   if(APP_PERSBEST_ACTIVE && !APP_IS_CHEATER && !APP_IS_PRACTISE)
   {
      if(APP_PERSBEST_LEV.score < _loc1_)
      {
         userdata.SubmitPersBest_Level(gamedata.curEpisode,gamedata.curLevel,_loc1_);
         App_PersBestLevel_DemoReady(_loc2_);
      }
   }
   App_StartFinishedTimeTrial();
}
function App_EpisodeLevel_DemoReady(str)
{
   App_ResetGameTime();
   APP_PERSBEST_EPDEMOS[APP_PERSBEST_PENDINGLEVNUM] = str;
}
function App_PersBestEpLevel_DemoReady(str)
{
   gui.TextBarNotify(0,"[new personal best]  Episode " + gamedata.curEpisode + " Level " + APP_PERSBEST_PENDINGLEVNUM);
   App_ResetGameTime();
   userdata.SubmitPersBest_Level_Finish(str);
   APP_PERSBEST_EPDEMOS[APP_PERSBEST_PENDINGLEVNUM] = str;
   if(APP_PERSBEST_EPISBEST)
   {
      gui.TextBarNotify(1,"[new personal best] Episode " + APP_PERSBEST_EP_NUM);
   }
   APP_PERSBEST_EP_PENDING = APP_PERSBEST_EPISBEST = false;
}
function App_PersBestLevel_DemoReady(str)
{
   gui.TextBarNotify(0,"[new personal best]  Episode " + gamedata.curEpisode + " Level " + gamedata.curLevel);
   App_ResetGameTime();
   userdata.SubmitPersBest_Level_Finish(str);
}
function App_OnlineReplaySent_Episode_Active(isValid)
{
   var _loc1_;
   var _loc2_;
   if(isValid)
   {
      _loc1_ = onlineclient.GetLoadedData();
      _loc2_ = _loc1_.epnum;
      gui.TextBarNotify(3,"[new online highscore]  Episode " + _loc2_);
   }
}
function App_OnlineReplaySent_EpisodeAndLevel_Active(isValid)
{
   var _loc1_;
   var _loc2_;
   var _loc3_;
   if(isValid)
   {
      _loc1_ = onlineclient.GetLoadedData();
      _loc2_ = _loc1_.epnum;
      _loc3_ = _loc1_.levnum;
      gui.TextBarNotify(3,"[new online highscore]  Episode " + _loc2_);
      gui.TextBarNotify(2,"[new online highscore]  Episode " + _loc2_ + " Level " + _loc3_);
   }
}
function App_OnlineReplaySent_Level_Active(isValid)
{
   var _loc1_;
   var _loc2_;
   var _loc3_;
   if(isValid)
   {
      _loc1_ = onlineclient.GetLoadedData();
      _loc2_ = _loc1_.epnum;
      _loc3_ = _loc1_.levnum;
      gui.TextBarNotify(2,"[new online highscore]  Episode " + _loc2_ + " Level " + _loc3_);
   }
}
function App_LevelPassedEvent_Debug()
{
   console.AddLine("level completed.");
}
function App_LevelPassedEvent_Demo()
{
   objects.IdleObjectsAfterDeath();
}
function App_StartBeatGame()
{
   var _loc1_ = Math.random();
   if(_loc1_ < 0.14285714285714285)
   {
      gui.Display(GUI_VICTORY1);
   }
   else if(_loc1_ < 0.2857142857142857)
   {
      gui.Display(GUI_VICTORY2);
   }
   else if(_loc1_ < 0.42857142857142855)
   {
      gui.Display(GUI_VICTORY3);
   }
   else if(_loc1_ < 0.5714285714285714)
   {
      gui.Display(GUI_VICTORY4);
   }
   else if(_loc1_ < 0.7142857142857143)
   {
      gui.Display(GUI_VICTORY5);
   }
   else if(_loc1_ < 0.8571428571428571)
   {
      gui.Display(GUI_VICTORY6);
   }
   else
   {
      gui.Display(GUI_VICTORY7);
   }
   gui.DisplayTextBar(GUI_BEATGAME);
   App_TestForSecret0();
   SetActiveProcess(App_TickBeatGame);
}
function App_TickBeatGame()
{
   App_UpdateGame_Demo(false,false);
   if(APP_KEY_TRIG && Key.isDown(32))
   {
      userdata.Save();
      App_LoadMainMenu();
   }
}
function App_StartPassedEpisode(num)
{
   gui.HideAll();
   var _loc1_ = Math.random();
   if(_loc1_ < 0.14285714285714285)
   {
      gui.Display(GUI_VICTORY1);
   }
   else if(_loc1_ < 0.2857142857142857)
   {
      gui.Display(GUI_VICTORY2);
   }
   else if(_loc1_ < 0.42857142857142855)
   {
      gui.Display(GUI_VICTORY3);
   }
   else if(_loc1_ < 0.5714285714285714)
   {
      gui.Display(GUI_VICTORY4);
   }
   else if(_loc1_ < 0.7142857142857143)
   {
      gui.Display(GUI_VICTORY5);
   }
   else if(_loc1_ < 0.8571428571428571)
   {
      gui.Display(GUI_VICTORY6);
   }
   else
   {
      gui.Display(GUI_VICTORY7);
   }
   gui.DisplayTextBar(GUI_PASSEDEPISODE);
   var _loc2_ = num - 1;
   gui.AppendToTextBar("episode [" + _loc2_ + "] complete!!  [spacebar] to continue, [Q] for mainmenu");
   gamedata.LoadEpisodeNum(num);
   SetActiveProcess(App_TickPassedEpisode);
}
function App_TickPassedEpisode()
{
   App_UpdateGame_Demo(false,false);
   if(APP_KEY_TRIG && Key.isDown(32))
   {
      gui.HideInGame();
      App_StartNewGame();
   }
   else if(APP_KEY_TRIG && Key.isDown(81))
   {
      APP_KEY_TRIG = false;
      gui.HideInGame();
      userdata.Save();
      App_LoadMainMenu();
   }
}
function App_StartFinishedTimeTrial()
{
   var _loc2_ = _root._url;
   if(_loc2_.substr(0,4) != "file")
   {
      getURL("http://www.harveycartel.org/metanet/",_top);
   }
   gui.HideAll();
   gui.DisplayTextBar(GUI_POSTLEVELTIMETRIAL);
   SetActiveProcess(App_TickFinishedTimeTrial);
}
function App_TickFinishedTimeTrial()
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
      GUIEvent_MainMenu_TimeTrial(true);
   }
   else
   {
      App_UpdateGame_Demo(false,false);
      gui.DrawPlayerTime(APP_HACKY_REAL_TIME,game.playerMaxTime);
   }
}
function App_StartNewGame()
{
   console.Show();
   APP_GAME_WAS_PLAYED = true;
   var _loc1_ = new Sound();
   _loc1_.stop();
   game.InitNewGame(0);
   App_PlayerDeathEvent = App_PlayerDeathEvent_Normal;
   App_LevelPassedEvent = App_LevelPassedEvent_Normal;
   App_PlayGame = App_PlayGame_Normal;
   APP_ONLINE_ACTIVE = userdata.GetOnlineActive() && !APP_IS_CHEATER && !APP_IS_PRACTISE;
   APP_ONLINEGOAL_VALID = false;
   APP_ONLINEGOAL_EPISODE = -1;
   APP_ONLINEGOAL_LEVLIST = new Array();
   APP_ONLINEGOAL_LEVLIST[0] = -1;
   APP_ONLINEGOAL_LEVLIST[1] = -1;
   APP_ONLINEGOAL_LEVLIST[2] = -1;
   APP_ONLINEGOAL_LEVLIST[3] = -1;
   APP_ONLINEGOAL_LEVLIST[4] = -1;
   if(APP_ONLINE_ACTIVE)
   {
      onlineclient.QueryOnlineGoal_Episode(gamedata.curEpisode,App_ReceiveOnlineGoal_Normal);
   }
   APP_PERSBEST_ACTIVE = userdata.GetPersBestActive() && !APP_IS_CHEATER && !APP_IS_PRACTISE;
   if(APP_PERSBEST_ACTIVE)
   {
      APP_PERSBEST_EP = userdata.GetPersBest_Episode(gamedata.curEpisode);
   }
   APP_KEYDEF_PAUSE = userdata.GetPauseKey();
   APP_KEYDEF_KILL = userdata.GetKillKey();
   gui.Display(GUI_LOADINGLEVEL);
   App_LoadLevel(0,App_StartPreLevelPause);
}
function App_ReceiveOnlineGoal_Normal(isValid)
{
   console.AddLine("ReceiveOnlineGoal_Normal : " + isValid);
   var _loc1_;
   if(isValid)
   {
      _loc1_ = onlineclient.GetLoadedData();
      APP_ONLINEGOAL_EPISODE = _loc1_.escore;
      APP_ONLINEGOAL_LEVLIST = new Array();
      APP_ONLINEGOAL_LEVLIST[0] = _loc1_.score0;
      APP_ONLINEGOAL_LEVLIST[1] = _loc1_.score1;
      APP_ONLINEGOAL_LEVLIST[2] = _loc1_.score2;
      APP_ONLINEGOAL_LEVLIST[3] = _loc1_.score3;
      APP_ONLINEGOAL_LEVLIST[4] = _loc1_.score4;
      console.AddLine("ReceiveOnlineGoal_Normal goal: " + APP_ONLINEGOAL_EPISODE);
      APP_ONLINEGOAL_VALID = true;
   }
}
function App_StartNewTimeTrial(ep, lev)
{
   console.Show();
   APP_GAME_WAS_PLAYED = true;
   var _loc1_ = new Sound();
   _loc1_.stop();
   game.InitNewGame(1);
   App_PlayerDeathEvent = App_PlayerDeathEvent_Normal;
   App_LevelPassedEvent = App_LevelPassedEvent_TimeTrial;
   App_PlayGame = App_PlayGame_TimeTrial;
   APP_KEYDEF_PAUSE = userdata.GetPauseKey();
   APP_KEYDEF_KILL = userdata.GetKillKey();
   APP_ONLINE_ACTIVE = userdata.GetOnlineActive() && !APP_IS_CHEATER && !APP_IS_PRACTISE;
   APP_ONLINEGOAL_VALID = false;
   APP_ONLINEGOAL_LEVEL = -1;
   if(APP_ONLINE_ACTIVE)
   {
      onlineclient.QueryOnlineGoal_Level(ep,lev,App_ReceiveOnlineGoal_TimeTrial);
   }
   APP_PERSBEST_ACTIVE = userdata.GetPersBestActive();
   if(APP_PERSBEST_ACTIVE)
   {
      APP_PERSBEST_LEV = userdata.GetPersBest_Level(ep,lev);
   }
   gamedata.LoadEpisodeNum(ep);
   gamedata.curLevel = lev;
   gui.Display(GUI_LOADINGLEVEL);
   App_LoadLevel(gamedata.GetCurrentLevelID(),App_StartPreLevelPause);
}
function App_ReceiveOnlineGoal_TimeTrial(isValid)
{
   console.AddLine("ReceiveOnlineGoal_TimeTrial: " + isValid);
   var _loc1_;
   if(isValid)
   {
      _loc1_ = onlineclient.GetLoadedData();
      APP_ONLINEGOAL_LEVEL = _loc1_.score;
      console.AddLine("ReceiveOnlineGoal_TimeTrial goal: " + APP_ONLINEGOAL_LEVEL);
      APP_ONLINEGOAL_VALID = true;
   }
}
function App_StartPreLevelPause()
{
   APP_WAITING_TO_RETRY = false;
   console.Hide();
   if(game.isTimeTrial)
   {
      gui.Display(GUI_PRELEVELTIMETRIAL);
   }
   else if(game.isCustom)
   {
      gui.Display(GUI_PRELEVELCUSTOM);
   }
   else if(APP_IS_PRACTISE)
   {
      gui.Display(GUI_PRELEVELPRACTISE);
   }
   else
   {
      gui.Display(GUI_PRELEVEL);
   }
   if(APP_IS_PRACTISE)
   {
      gui.ShowInGame_Practise();
   }
   else
   {
      gui.ShowInGame();
   }
   var _loc1_ = new Sound();
   _loc1_.setVolume(0);
   game.InitRetryLevel();
   gui.ResetPlayerTime();
   var _loc2_;
   if(game.isCustom)
   {
      _loc2_ = APP_CUSTOM_LEVELNAME + "  ( by " + APP_CUSTOM_AUTHORNAME + " )";
      gui.DrawLevelName(_loc2_);
   }
   else
   {
      gui.DrawLevelName(gamedata.GetCurrentLevelName());
   }
   userdata.Save();
   SetActiveProcess(App_Tick_PreLevelPause);
}
function App_Tick_PreLevelPause()
{
   if(!APP_IS_PRACTISE)
   {
      game.FillPlayerTime();
   }
   var _loc1_;
   if(APP_KEY_TRIG && Key.isDown(32))
   {
      APP_KEY_TRIG = false;
      _loc1_ = new Sound();
      _loc1_.setVolume(Math.round(userdata.GetVol()));
      App_OnlineReplaySent_EpisodeAndLevel = null;
      App_OnlineReplaySent_Episode = null;
      App_OnlineReplaySent_Level = null;
      App_PlayGame();
   }
   if(Key.isDown(81))
   {
      if(game.isTimeTrial)
      {
         APP_KEY_TRIG = false;
         userdata.Save();
         GUIEvent_MainMenu_TimeTrial(true);
      }
      else if(game.isCustom)
      {
         APP_KEY_TRIG = false;
         userdata.Save();
         GUIEvent_MainMenu_Custom(false);
      }
      else
      {
         APP_KEY_TRIG = false;
         gui.HideInGame();
         userdata.Save();
         App_LoadMainMenu();
      }
   }
   if(!game.isTimeTrial && APP_IS_PRACTISE && !game.isCustom)
   {
      if(Key.isDown(13))
      {
         App_ResetGameTime();
         App_LevelPassedEvent();
         userdata.Save();
         App_PostLevelResponse();
      }
   }
}
function App_PlayGame_Normal()
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
   App_LevelPassedEvent = App_LevelPassedEvent_Normal;
   APP_EPLEV_STARTTIME = game.GetPlayerTime();
   SetActiveProcess(App_Tick_RunningGame);
}
function App_PlayGame_TimeTrial()
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
   App_LevelPassedEvent = App_LevelPassedEvent_TimeTrial;
   SetActiveProcess(App_Tick_RunningGame);
}
function App_UnpauseGame()
{
   gui.HideAll();
   App_ResetGameTime();
   SetActiveProcess(App_Tick_RunningGame);
}
function App_Tick_RunningGame()
{
   var _loc1_ = APP_KEY_TRIG && !player.isDead;
   var _loc2_;
   if(_loc1_ && Key.isDown(APP_KEYDEF_PAUSE) || _loc1_ && Key.isDown(27))
   {
      APP_KEY_TRIG = false;
      App_PauseGame();
   }
   else
   {
      if(APP_KEY_TRIG && Key.isDown(APP_KEYDEF_KILL))
      {
         APP_KEY_TRIG = false;
         APP_VOLUNTARY_SUICIDE = true;
         if(Math.random() < 0.3)
         {
            game.KillPlayer(KILLTYPE_EXPLOSIVE,Math.random() * 10 - 5,(- Math.random()) * 6,player.pos.x,player.pos.y,player);
         }
         else
         {
            game.KillPlayer(KILLTYPE_HARDBULLET,Math.random() * 10 - 5,(- Math.random()) * 6,player.pos.x,player.pos.y,player);
         }
      }
      if(player.isDead)
      {
         App_UpdateGame_Demo(false,false);
         if(APP_KEY_TRIG && Key.isDown(32))
         {
            APP_KEY_TRIG = false;
            _loc2_ = new Sound();
            _loc2_.stop();
            App_ResetObjects(App_StartPreLevelPause);
            return undefined;
         }
         if(APP_WAITING_TO_RETRY)
         {
            if(APP_KEY_TRIG && Key.isDown(32))
            {
               APP_KEY_TRIG = false;
               _loc2_ = new Sound();
               _loc2_.stop();
               App_ResetObjects(App_StartPreLevelPause);
            }
            else if(!APP_VOLUNTARY_SUICIDE)
            {
               if(Key.isDown(82))
               {
                  APP_KEY_TRIG = false;
                  _loc2_ = new Sound();
                  _loc2_.stop();
                  APP_REPLAY_DATA = game.DumpDemoData(false);
                  App_StartInGameDemo();
               }
            }
         }
         else if(40 < game.GetTime() - player.timeOfDeath)
         {
            game.StopRecordingDemo();
            App_StartRetryMenu(APP_VOLUNTARY_SUICIDE);
         }
      }
      else
      {
         App_UpdateGame();
         if(game.playerCurTime <= 0)
         {
            game.KillPlayer(KILLTYPE_FALL,0,0,player.pos.x,player.pos.y,player);
         }
      }
   }
}
function App_UpdateGame()
{
   var _loc2_ = APP_GAMETIME_t0;
   APP_GAMETIME_t0 = APP_t0;
   var _loc1_ = APP_GAMETIME_t0 - _loc2_ + APP_GAMETIME_REMAINDER;
   _loc1_ = (_loc1_ + APP_GAMETIME_SMOOTHAMT * APP_PREV_MS) / (1 + APP_GAMETIME_SMOOTHAMT);
   APP_PREV_MS = _loc1_;
   var _loc3_ = _loc1_;
   if(2000 < _loc1_)
   {
      console.AddLine("resetting clock->too much lag");
      _loc1_ = APP_GAMETIME_TICKLEN;
   }
   while(APP_GAMETIME_TICKLEN <= _loc1_)
   {
      _loc1_ -= APP_GAMETIME_TICKLEN;
      game.Tick();
      if(!APP_IS_PRACTISE)
      {
         game.playerCurTime--;
      }
   }
   APP_GAMETIME_REMAINDER = _loc1_;
   if(_loc1_ < _loc3_)
   {
      game.Draw();
      if(!APP_IS_PRACTISE)
      {
         game.DrawPlayerTime();
      }
   }
}
function App_UpdateGame_Demo(tickTime, realtime)
{
   var _loc3_ = APP_GAMETIME_t0;
   APP_GAMETIME_t0 = APP_t0;
   var _loc1_ = APP_GAMETIME_t0 - _loc3_ + APP_GAMETIME_REMAINDER;
   var _loc4_ = _loc1_;
   if(2000 < _loc1_)
   {
      console.AddLine("resetting clock->too much lag");
      _loc1_ = APP_GAMETIME_TICKLEN;
   }
   while(APP_GAMETIME_TICKLEN <= _loc1_)
   {
      _loc1_ -= APP_GAMETIME_TICKLEN;
      game.Tick();
      if(tickTime)
      {
         game.playerCurTime--;
      }
   }
   APP_GAMETIME_REMAINDER = _loc1_;
   if(_loc1_ < _loc4_)
   {
      game.Draw();
   }
}
function App_ResetGameTime()
{
   APP_GAMETIME_t0 = APP_t0;
   APP_GAMETIME_REMAINDER = 0;
   APP_PREV_MS = 0;
}
function App_PauseGame()
{
   gui.Display(GUI_PAUSE);
   SetActiveProcess(App_Tick_InGamePause);
}
function App_Tick_InGamePause()
{
   var _loc1_;
   if(APP_KEY_TRIG && Key.isDown(32) || APP_KEY_TRIG && Key.isDown(APP_KEYDEF_PAUSE))
   {
      APP_KEY_TRIG = false;
      App_UnpauseGame();
   }
   else if(APP_KEY_TRIG && Key.isDown(81))
   {
      if(game.isTimeTrial)
      {
         APP_KEY_TRIG = false;
         userdata.Save();
         GUIEvent_MainMenu_TimeTrial(true);
      }
      else if(game.isCustom)
      {
         APP_KEY_TRIG = false;
         _loc1_ = new Sound();
         _loc1_.stop();
         userdata.Save();
         GUIEvent_MainMenu_Custom(false);
      }
      else
      {
         APP_KEY_TRIG = false;
         gui.HideInGame();
         userdata.Save();
         App_LoadMainMenu();
      }
   }
   else
   {
      APP_KEY_TRIG = false;
   }
}
function App_StartPostLevelPause(POSTLEV_STATE)
{
   if(POSTLEV_STATE == APP_POSTLEVEL_NEXTLEV)
   {
      gui.Display(GUI_POSTLEVEL);
      App_PostLevelResponse = App_PostLevelResponse_NextLevel;
   }
   else if(POSTLEV_STATE == APP_POSTLEVEL_NEXTEP)
   {
      gui.Display(GUI_POSTLEVEL);
      App_PostLevelResponse = App_PostLevelResponse_NextEpisode;
   }
   App_ResetGameTime();
   if(game.isCustom)
   {
      APP_CUSTOM_REPLAY_RAWDATA = game.DumpDemoData(false);
   }
   SetActiveProcess(App_Tick_PostLevelPause);
}
function App_Tick_PostLevelPause()
{
   if(Key.isDown(32))
   {
      userdata.Save();
      App_PostLevelResponse();
   }
   else if(Key.isDown(82))
   {
      APP_REPLAY_DATA = game.DumpDemoData(false);
      App_Start_PostLevelPause_Demo();
   }
   else
   {
      App_UpdateGame_Demo(false,false);
      if(!APP_IS_PRACTISE)
      {
         gui.DrawPlayerTime(APP_HACKY_REAL_TIME,game.playerMaxTime);
      }
   }
}
function App_Start_PostLevelPause_Demo()
{
   var _loc1_ = new Sound();
   _loc1_.stop();
   App_PlayerDeathEvent = App_PlayerDeathEvent_Demo;
   App_LevelPassedEvent = App_LevelPassedEvent_Demo;
   App_ResetGameTime();
   game.SetDemoFormat(false);
   game.InitRetryLevel();
   game.StopDemoPlayback();
   game.LoadDemo(APP_REPLAY_DATA);
   game.StartDemoPlayback();
   App_ResetObjects(App_Tick_PostLevelPause_Demo);
   gui.Display(GUI_POSTLEVDEMO);
   APP_DEMO_DELAY_COUNTER = 0;
}
function App_Tick_PostLevelPause_Demo()
{
   var _loc1_;
   if(Key.isDown(32))
   {
      APP_KEY_TRIG = false;
      _loc1_ = new Sound();
      _loc1_.stop();
      userdata.Save();
      App_PostLevelResponse();
   }
   else if(game.GetDemoTickCount() - game.GetTime() < -130)
   {
      _loc1_ = new Sound();
      _loc1_.stop();
      App_Start_PostLevelPause_Demo();
   }
   else if(APP_DEMO_DELAY_AMT < APP_DEMO_DELAY_COUNTER)
   {
      App_UpdateGame_Demo(false,false);
   }
   else
   {
      APP_DEMO_DELAY_COUNTER++;
      App_ResetGameTime();
   }
}
function App_StartRetryMenu(suicide)
{
   if(suicide)
   {
      gui.Display(GUI_RETRYLEVEL_SUICIDE);
   }
   else
   {
      gui.Display(GUI_RETRYLEVEL);
   }
   APP_WAITING_TO_RETRY = true;
}
function App_StartGameOver()
{
   gui.Display(GUI_DEFEAT);
   gui.DisplayTextBar(GUI_GAMEOVER);
   SetActiveProcess(App_Tick_GameOver);
}
function App_Tick_GameOver()
{
   if(Key.isDown(32))
   {
      userdata.Save();
      App_LoadMainMenu();
   }
   else
   {
      App_UpdateGame_Demo(false,false);
   }
}
function App_StartInGameDemo()
{
   App_PlayerDeathEvent = App_PlayerDeathEvent_Demo;
   App_LevelPassedEvent = App_LevelPassedEvent_Demo;
   App_ResetGameTime();
   APP_DEBUG_DEATH = true;
   game.SetDemoFormat(false);
   game.InitRetryLevel();
   game.StopDemoPlayback();
   game.LoadDemo(APP_REPLAY_DATA);
   game.StartDemoPlayback();
   App_ResetObjects(App_TickInGameDemo);
   gui.Display(GUI_INGAMEDEMO);
   APP_DEMO_DELAY_COUNTER = 0;
}
function App_TickInGameDemo()
{
   var _loc1_;
   if(Key.isDown(32))
   {
      APP_KEY_TRIG = false;
      _loc1_ = new Sound();
      _loc1_.stop();
      App_ResetObjects(App_StartPreLevelPause);
   }
   else if(game.GetDemoTickCount() - game.GetTime() < -130)
   {
      _loc1_ = new Sound();
      _loc1_.stop();
      App_StartInGameDemo();
   }
   else if(APP_DEMO_DELAY_AMT < APP_DEMO_DELAY_COUNTER)
   {
      App_UpdateGame_Demo(false,false);
   }
   else
   {
      APP_DEMO_DELAY_COUNTER++;
      App_ResetGameTime();
   }
}
APP_REPLAY_DATA = "";
APP_VICTORY = false;
APP_DEMO_DELAY_AMT = 20;
APP_DEMO_DELAY_COUNTER = 0;
APP_POSTLEVEL_NEXTLEV = 1;
APP_POSTLEVEL_NEXTEP = 2;
APP_POSTLEVEL_TIMETRIAL = 3;
App_PostLevelResponse = App_PostLevelResponse_NextLevel;
APP_EPLEV_STARTTIME = 0;
APP_PERSBEST_ACTIVE = false;
APP_PERSBEST_PENDINGLEVNUM = 0;
APP_PERSBEST_LEV = null;
APP_PERSBEST_EP = null;
APP_PERSBEST_EPDEMOS = new Array();
APP_PERSBEST_EPDEMOS[0] = "";
APP_PERSBEST_EPDEMOS[1] = "";
APP_PERSBEST_EPDEMOS[2] = "";
APP_PERSBEST_EPDEMOS[3] = "";
APP_PERSBEST_EPDEMOS[4] = "";
APP_PERSBEST_EPISBEST = false;
APP_PERSBEST_EP_TIME = 0;
APP_PERSBEST_EP_NUM = 0;
APP_PERSBEST_EP_PENDING = false;
APP_ONLINE_ACTIVE = false;
APP_ONLINEGOAL_VALID = false;
APP_ONLINEGOAL_EPISODE = 0;
APP_ONLINEGOAL_LEVEL = 0;
APP_ONLINEGOAL_LEVLIST = new Array();
APP_ONLINEGOAL_LEVLIST[0] = 0;
APP_ONLINEGOAL_LEVLIST[1] = 0;
APP_ONLINEGOAL_LEVLIST[2] = 0;
APP_ONLINEGOAL_LEVLIST[3] = 0;
APP_ONLINEGOAL_LEVLIST[4] = 0;
APP_HACKY_REAL_TIME = 0;
APP_BEAT_TIME = 0;
APP_IS_CHEATER = false;
APP_DEBUG_DEATH = false;
APP_IS_PRACTISE = false;
APP_GAME_WAS_PLAYED = false;
APP_GAMETIME_t0 = 0;
APP_GAMETIME_REMAINDER = 0;
APP_PREV_MS = 0;
