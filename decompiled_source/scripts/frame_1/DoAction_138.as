function App_StartHighscoreMenu(isReset)
{
   gui.HideInGame();
   gui.Display(GUI_HIGHSCOREMENU);
   SetActiveProcess(App_TickHighscoreMenu);
   APP_DEBUG_DEATH = true;
   APP_CURRENTHIGHSCOREMODE = APP_HIGHSCOREMODE_MENU;
   var menuMC = gui.GetCurrentMC();
   var scoreMC = eval(menuMC + ".scoremenu");
   scoreMC.recPanel._visible = false;
   scoreMC.toggleButton._visible = false;
   scoreMC.toggleButton.onRelease = function()
   {
      _root.App_HighscoreMenu_ToggleClicked(this);
   };
   scoreMC.timetrialButton.state.text = "play level";
   scoreMC.timetrialButton._visible = true;
   scoreMC.timetrialButton.onRelease = function()
   {
      var _loc1_;
      var _loc2_;
      if(0 <= APP_HS_CURRENTLEVEL_TT && 0 <= APP_HS_CURRENTEPISODE_TT)
      {
         _loc1_ = APP_HS_CURRENTEPISODE_TT;
         _loc2_ = APP_HS_CURRENTLEVEL_TT;
         APP_IS_PRACTISE = userdata.GetPractiseMode();
         APP_IS_CHEATER = APP_HS_CURRENTLEVEL_TT_CHEATER;
         APP_HIGHSCORE_REPLAY_READY = false;
         App_StartNewTimeTrial(_loc1_,_loc2_);
      }
   };
   scoreMC.submitButton.state.text = "submit";
   scoreMC.submitButton._visible = true;
   scoreMC.submitButton.onRelease = function()
   {
      _root.App_HighscoreMenu_SubmitClicked(this);
   };
   var klist = userdata.GetKillList();
   var killMC = eval(scoreMC + ".killPanel");
   killMC._visible = true;
   for(var i in klist)
   {
      var txtbox = killMC[i];
      txtbox.text = klist[i];
   }
   scoreMC.epPanel.pbutE.p = -1;
   scoreMC.epPanel.pbut0.p = 0;
   scoreMC.epPanel.pbut1.p = 1;
   scoreMC.epPanel.pbut2.p = 2;
   scoreMC.epPanel.pbut3.p = 3;
   scoreMC.epPanel.pbut4.p = 4;
   var epReached = new Array();
   epReached[0] = userdata.GetEpisodeReached(0);
   epReached[1] = userdata.GetEpisodeReached(1);
   epReached[2] = userdata.GetEpisodeReached(2);
   epReached[3] = userdata.GetEpisodeReached(3);
   epReached[4] = userdata.GetEpisodeReached(4);
   epReached[5] = userdata.GetEpisodeReached(5);
   epReached[6] = userdata.GetEpisodeReached(6);
   epReached[7] = userdata.GetEpisodeReached(7);
   epReached[8] = userdata.GetEpisodeReached(8);
   epReached[9] = userdata.GetEpisodeReached(9);
   var epBeaten = new Array();
   epBeaten[0] = userdata.GetEpisodeBeaten(0);
   epBeaten[1] = userdata.GetEpisodeBeaten(1);
   epBeaten[2] = userdata.GetEpisodeBeaten(2);
   epBeaten[3] = userdata.GetEpisodeBeaten(3);
   epBeaten[4] = userdata.GetEpisodeBeaten(4);
   epBeaten[5] = userdata.GetEpisodeBeaten(5);
   epBeaten[6] = userdata.GetEpisodeBeaten(6);
   epBeaten[7] = userdata.GetEpisodeBeaten(7);
   epBeaten[8] = userdata.GetEpisodeBeaten(8);
   epBeaten[9] = userdata.GetEpisodeBeaten(9);
   var i = 0;
   while(i < 100)
   {
      var but = eval(scoreMC + ".epPanel" + ".e" + i);
      if(i < 10)
      {
         but.num.text = "0" + i;
      }
      else
      {
         but.num.text = "" + i;
      }
      var setnum = Math.floor(i / 10);
      var epR = epReached[setnum];
      var epB = epBeaten[setnum];
      if(i <= epB)
      {
         but.progressType = 1;
      }
      else if(i <= epR)
      {
         but.progressType = 3;
      }
      else
      {
         but.progressType = 4;
      }
      but.gfx.gotoAndStop(but.progressType);
      but.onRollOver = function()
      {
         this.gfx.gotoAndStop(2);
      };
      but.onRollOut = function()
      {
         this.gfx.gotoAndStop(this.progressType);
      };
      but.onReleaseOutside = function()
      {
         this.gfx.gotoAndStop(this.progressType);
      };
      but.onRelease = function()
      {
         _root.App_HighscoreEpisodeButtonClicked(this,true);
      };
      i++;
   }
   if(!isReset)
   {
      App_HighscoreEpisodeButtonClicked(APP_HIGHSCORE_CUR_SELECTED,false);
      scoreMC.toggleButton._visible = false;
   }
   else
   {
      App_HighscoreEpisodeButtonClicked(null,true);
      scoreMC.toggleButton._visible = false;
   }
}
function App_TickHighscoreMenu()
{
   if(APP_CURRENTHIGHSCOREMODE == APP_HIGHSCOREMODE_PLAYING)
   {
      if(APP_HIGHSCORE_REPLAY_READY)
      {
         App_UpdateHighscoreMenu_PlayReplay();
      }
   }
}
function App_UpdateHighscoreMenu_PlayReplay()
{
   var _loc1_;
   if(!App_TickHighscoreReplay())
   {
      _loc1_ = new Sound();
      _loc1_.stop();
      game.StopDemoPlayback();
      App_StartLoadingNextHighscoreReplay();
   }
}
function App_HighscoreEpisodeButtonClicked(but, isNew)
{
   var s = new Sound();
   s.stop();
   _root.APP_PERSBEST_ONLINE = new Object();
   APP_CURRENTHIGHSCOREMODE = APP_HIGHSCOREMODE_MENU;
   var menuMC = gui.GetCurrentMC();
   var scoreMC = eval(menuMC + ".scoremenu");
   scoreMC.epPanel._visible = true;
   scoreMC.recPanel._visible = true;
   scoreMC.killPanel._visible = true;
   scoreMC.toggleButton.state.text = "return to replay";
   scoreMC.toggleButton._visible = APP_HIGHSCORE_REPLAY_READY || !isNew && !isReset;
   scoreMC.submitButton._visible = true;
   scoreMC.statusbox._visible = true;
   var isNull = false;
   var num = 0;
   if(but == null)
   {
      txt = "--";
      isNull = true;
      APP_HS_CURRENTEPISODE_TT = -1;
   }
   else
   {
      var txt = but.num.text;
      num = Number(txt);
      APP_HS_CURRENTEPISODE_TT = num;
   }
   scoreMC.epPanel.eptitle.text = "episode " + txt;
   if(APP_HIGHSCORE_CUR_SELECTED != null)
   {
      APP_HIGHSCORE_CUR_SELECTED.gfx.gotoAndStop(APP_HIGHSCORE_CUR_SELECTED.progressType);
      APP_HIGHSCORE_CUR_SELECTED.onRollOver = function()
      {
         this.gfx.gotoAndStop(2);
      };
      APP_HIGHSCORE_CUR_SELECTED.onRollOut = function()
      {
         this.gfx.gotoAndStop(this.progressType);
      };
   }
   if(!isNull)
   {
      APP_HIGHSCORE_CUR_SELECTED = but;
      APP_HIGHSCORE_CUR_SELECTED.gfx.gotoAndStop(2);
      APP_HIGHSCORE_CUR_SELECTED.onRollOver = null;
      APP_HIGHSCORE_CUR_SELECTED.onRollOut = null;
      scoreMC.timetrialButton._visible = false;
   }
   if(isNull)
   {
      scoreMC.statusbox.msg.text = "please select an episode.";
   }
   if(isNew && !isNull)
   {
      _root.APP_PERSBEST_ONLINE = new Object();
      APP_HIGHSCORE_ONLINE_EP = num;
      scoreMC.statusbox.msg.text = "";
      scoreMC.statusbox.msg.text += "downloading records..";
      onlineclient.QueryTopRecords(num,App_ReceiveOnlineRecords);
   }
   if(isNull)
   {
      var pbut = eval(scoreMC + ".epPanel" + ".pbutE");
      pbut.gfx.gotoAndStop(4);
      pbut.onRollOver = null;
      pbut.onRollOut = null;
      pbut.onRelease = null;
      pbut.onReleaseOutside = null;
      var i = 0;
      while(i < 5)
      {
         var pbut = eval(scoreMC + ".epPanel" + ".pbut" + i);
         pbut.gfx.gotoAndStop(4);
         pbut.onRollOver = null;
         pbut.onRollOut = null;
         pbut.onRelease = null;
         pbut.onReleaseOutside = null;
         i++;
      }
      APP_HIGHSCORE_CUR_PANEL = null;
      App_HighscoreMenu_ViewPanel(scoreMC.epPanel.pbutE);
   }
   else if(isNew)
   {
      App_HighscoreMenu_ViewPanel(scoreMC.epPanel.pbutE);
      var pbut = eval(scoreMC + ".epPanel" + ".pbutE");
      pbut.progressType = but.progressType;
      var tempPT = pbut.progressType;
      pbut.gfx.gotoAndStop(tempPT);
      pbut.onRollOver = function()
      {
         this.gfx.gotoAndStop(2);
      };
      pbut.onRollOut = function()
      {
         this.gfx.gotoAndStop(this.progressType);
      };
      pbut.onRelease = function()
      {
         _root.App_HighscoreMenu_ViewPanel(this);
      };
      pbut.onReleaseOutside = function()
      {
         this.gfx.gotoAndStop(this.progressType);
      };
      var levR = userdata.GetLevelReached(APP_HS_CURRENTEPISODE_TT);
      var levB = userdata.GetLevelBeaten(APP_HS_CURRENTEPISODE_TT);
      var i = 0;
      while(i < 5)
      {
         var pbut = eval(scoreMC + ".epPanel" + ".pbut" + i);
         if(but.progressType == 4)
         {
            pbut.progressType = 4;
         }
         else if(i <= levB && but.progressType == 1)
         {
            pbut.progressType = 1;
         }
         else if(i <= levR)
         {
            pbut.progressType = 3;
         }
         else
         {
            pbut.progressType = 4;
         }
         var tempPT = pbut.progressType;
         pbut.gfx.gotoAndStop(tempPT);
         pbut.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         pbut.onRollOut = function()
         {
            this.gfx.gotoAndStop(this.progressType);
         };
         pbut.onRelease = function()
         {
            _root.App_HighscoreMenu_ViewPanel(this);
         };
         pbut.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(this.progressType);
         };
         i++;
      }
   }
   else
   {
      App_HighscoreMenu_ViewPanel(APP_HIGHSCORE_CUR_PANEL);
   }
   if(isNull || isNew)
   {
      var i = 0;
      while(i < 20)
      {
         var recordMC = eval(scoreMC + ".recPanel.epPanel.record_" + i);
         recordMC.isOnline = true;
         recordMC.isEpisode = true;
         recordMC.isLoaded = false;
         recordMC.scorebox.text = "---.---";
         recordMC.username.text = "------------";
         recordMC.gfx._visible = false;
         recordMC.enabled = false;
         recordMC.onRelease = null;
         i++;
      }
      var i = 0;
      while(i < 5)
      {
         var recPanel = ".recPanel.lev" + i + "Panel.record_";
         var j = 0;
         while(j < 20)
         {
            var recordMC = eval(scoreMC + recPanel + j);
            recordMC.isEpisode = false;
            recordMC.isOnline = true;
            recordMC.isLoaded = false;
            recordMC.scorebox.text = "---.---";
            recordMC.username.text = "------------";
            recordMC.gfx._visible = false;
            recordMC.enabled = false;
            recordMC.onRelease = null;
            j++;
         }
         i++;
      }
      var p0 = eval(scoreMC + ".lev0Panel");
      var p1 = eval(scoreMC + ".lev0Panel");
      var p2 = eval(scoreMC + ".lev0Panel");
      var p3 = eval(scoreMC + ".lev0Panel");
      var p4 = eval(scoreMC + ".lev0Panel");
      p0._visible = false;
      p1._visible = false;
      p2._visible = false;
      p3._visible = false;
      p4._visible = false;
   }
   var tempShowSubmitButton = false;
   var recordMC = eval(scoreMC + ".recPanel.persbestPanel.record_pe");
   var epRec = userdata.GetPersBest_Episode(num);
   recordMC.isEpisode = true;
   if(!isNull && epRec.ep.demo0 != "" && epRec.ep.demo1 != "" && epRec.ep.demo2 != "" && epRec.ep.demo3 != "" && epRec.ep.demo4 != "")
   {
      tempShowSubmitButton = true;
      recordMC.valid = true;
      recordMC.scorebox.text = gui.FormatTime(epRec.ep.score);
      recordMC.score = epRec.ep.score;
      recordMC.demo0 = epRec.ep.demo0;
      recordMC.demo1 = epRec.ep.demo1;
      recordMC.demo2 = epRec.ep.demo2;
      recordMC.demo3 = epRec.ep.demo3;
      recordMC.demo4 = epRec.ep.demo4;
      recordMC.ep = num;
      recordMC.isOnline = false;
      recordMC.isEpisode = true;
      recordMC.gfx._visible = true;
      recordMC.enabled = true;
      recordMC.onRelease = function()
      {
         _root.App_HighscoreRecordButtonClicked(this,true);
      };
      APP_PERSBEST_ONLINE.ep = new Object();
      APP_PERSBEST_ONLINE.ep.epNum = num;
      APP_PERSBEST_ONLINE.ep.score = epRec.ep.score;
      APP_PERSBEST_ONLINE.ep.demo0 = epRec.ep.demo0;
      APP_PERSBEST_ONLINE.ep.demo1 = epRec.ep.demo1;
      APP_PERSBEST_ONLINE.ep.demo2 = epRec.ep.demo2;
      APP_PERSBEST_ONLINE.ep.demo3 = epRec.ep.demo3;
      APP_PERSBEST_ONLINE.ep.demo4 = epRec.ep.demo4;
   }
   else
   {
      APP_PERSBEST_ONLINE.ep = null;
      recordMC.onRelease = null;
      recordMC.enabled = false;
      recordMC.gotoAndStop(1);
      recordMC.valid = false;
      recordMC.scorebox.text = "---.---";
      recordMC.isOnline = false;
   }
   var i = 0;
   while(i < 5)
   {
      var recName = ".recPanel.persbestPanel.record_p0" + i;
      var recordMC = eval(scoreMC + recName);
      var levRec = userdata.GetPersBest_Level(num,i);
      recordMC.isEpisode = false;
      if(!isNull && levRec.demo != "")
      {
         tempShowSubmitButton = true;
         recordMC.valid = true;
         recordMC.score = levRec.score;
         recordMC.scorebox.text = gui.FormatTime(levRec.score);
         recordMC.demo = levRec.demo;
         recordMC.ep = num;
         recordMC.lev = i;
         recordMC.isOnline = false;
         recordMC.isEpisode = false;
         recordMC.gfx._visible = true;
         recordMC.enabled = true;
         recordMC.onRelease = function()
         {
            _root.App_HighscoreRecordButtonClicked(this,false);
         };
         APP_PERSBEST_ONLINE["lev" + i] = new Object();
         APP_PERSBEST_ONLINE["lev" + i].score = levRec.score;
         APP_PERSBEST_ONLINE["lev" + i].demo = levRec.demo;
         APP_PERSBEST_ONLINE["lev" + i].epNum = num;
         APP_PERSBEST_ONLINE["lev" + i].levNum = i;
      }
      else
      {
         APP_PERSBEST_ONLINE["lev" + i] = null;
         recordMC.valid = false;
         recordMC.scorebox.text = "---.---";
         recordMC.isOnline = false;
         recordMC.onRelease = null;
         recordMC.enabled = false;
         recordMC.gotoAndStop(1);
      }
      i++;
   }
   scoreMC.submitButton._visible = tempShowSubmitButton;
}
function App_HighscoreMenu_ViewPanel(but)
{
   if(APP_HIGHSCORE_CUR_PANEL != null)
   {
      var tempTP = APP_HIGHSCORE_CUR_PANEL.progressType;
      APP_HIGHSCORE_CUR_PANEL.gfx.gotoAndStop(tempTP);
      APP_HIGHSCORE_CUR_PANEL.onRollOver = function()
      {
         this.gfx.gotoAndStop(2);
      };
      APP_HIGHSCORE_CUR_PANEL.onRollOut = function()
      {
         this.gfx.gotoAndStop(this.progressType);
      };
      APP_HIGHSCORE_CUR_PANEL.onReleaseOutside = function()
      {
         this.gfx.gotoAndStop(this.progressType);
      };
      APP_HIGHSCORE_CUR_PANEL.onRelease = function()
      {
         _root.App_HighscoreMenu_ViewPanel(this);
      };
   }
   APP_HIGHSCORE_CUR_PANEL = but;
   APP_HIGHSCORE_CUR_PANEL.onRollOver = null;
   APP_HIGHSCORE_CUR_PANEL.onRollOut = null;
   APP_HIGHSCORE_CUR_PANEL.onRelease = null;
   APP_HIGHSCORE_CUR_PANEL.onReleaseOutside = null;
   APP_HIGHSCORE_CUR_PANEL.gfx.gotoAndStop(2);
   var p = but.p;
   var menuMC = gui.GetCurrentMC();
   var scoreMC = eval(menuMC + ".scoremenu");
   var ep = eval(scoreMC + ".recPanel.epPanel");
   if(p == -1)
   {
      ep._visible = true;
      scoreMC.timetrialButton._visible = false;
      APP_HS_CURRENTLEVEL_TT = -1;
   }
   else
   {
      ep._visible = false;
      APP_HS_CURRENTLEVEL_TT = p;
      if(but.progressType == 1)
      {
         scoreMC.timetrialButton._visible = true;
         scoreMC.timetrialButton.state.text = "play level " + p;
         APP_HS_CURRENTLEVEL_TT_CHEATER = false;
      }
      else if(but.progressType == 3)
      {
         scoreMC.timetrialButton._visible = true;
         scoreMC.timetrialButton.state.text = "play level " + p;
         APP_HS_CURRENTLEVEL_TT_CHEATER = true;
      }
      else
      {
         scoreMC.timetrialButton._visible = false;
      }
   }
   var i = 0;
   while(i < 5)
   {
      var pan = eval(scoreMC + ".recPanel.lev" + i + "Panel");
      if(i == p)
      {
         pan._visible = true;
      }
      else
      {
         pan._visible = false;
      }
      i++;
   }
}
function App_HighscoreMenu_ToggleClicked(but)
{
   if(APP_CURRENTHIGHSCOREMODE == APP_HIGHSCOREMODE_MENU)
   {
      App_ShowHighscoreReplay();
   }
   else if(APP_CURRENTHIGHSCOREMODE == APP_HIGHSCOREMODE_PLAYING)
   {
      App_ShowHighscoreMenu();
   }
}
function App_ShowHighscoreReplay()
{
   var s = new Sound();
   s.setVolume(Math.round(userdata.GetVol()));
   APP_CANCEL_AUTOPLAY = false;
   if(APP_HIGHSCORE_REPLAY_READY)
   {
      gui.ShowInGame();
      gui.DrawLevelName(gamedata.GetCurrentLevelName());
   }
   var menuMC = gui.GetCurrentMC();
   var scoreMC = eval(menuMC + ".scoremenu");
   scoreMC.epPanel._visible = false;
   scoreMC.recPanel._visible = false;
   scoreMC.killPanel._visible = false;
   scoreMC.toggleButton._visible = true;
   scoreMC.toggleButton.state.text = "return to menu";
   scoreMC.submitButton._visible = false;
   scoreMC.timetrialButton._visible = false;
   scoreMC.statusbox._visible = false;
   APP_CURRENTHIGHSCOREMODE = APP_HIGHSCOREMODE_PLAYING;
   App_ResetGameTime();
}
function App_ShowHighscoreMenu()
{
   var _loc1_ = new Sound();
   _loc1_.setVolume(0);
   gui.HideInGame();
   APP_CURRENTHIGHSCOREMODE = APP_HIGHSCOREMODE_MENU;
   APP_CANCEL_AUTOPLAY = true;
   App_ResetGameTime();
   App_HighscoreEpisodeButtonClicked(APP_HIGHSCORE_CUR_SELECTED,false);
}
function App_HighscoreRecordButtonClicked(but, isEpisode)
{
   _root.APP_REPLAY_DATA = new Object();
   APP_CANCEL_AUTOPLAY = false;
   if(but.isOnline)
   {
      if(but.isLoaded)
      {
         if(isEpisode)
         {
            var menuMC = gui.GetCurrentMC();
            var scoreMC = eval(menuMC + ".scoremenu");
            scoreMC.statusbox.msg.text = "downloading replay data..";
            onlineclient.QueryEpisodeDemo(but.pkey,App_ReceiveOnlineDemo_Episode);
         }
         else
         {
            var menuMC = gui.GetCurrentMC();
            var scoreMC = eval(menuMC + ".scoremenu");
            scoreMC.statusbox.msg.text = "downloading replay data..";
            onlineclient.QueryLevelDemo(but.pkey,App_ReceiveOnlineDemo_Level);
         }
      }
   }
   else if(but.valid)
   {
      APP_REPLAY_DATA.isEpisode = isEpisode;
      if(isEpisode)
      {
         APP_REPLAY_DATA.ep = but.ep;
         APP_REPLAY_DATA.lev = 0;
         APP_REPLAY_DATA.demoList = new Array();
         APP_REPLAY_DATA.score = but.score;
         APP_REPLAY_DATA.demoList[0] = but.demo0;
         APP_REPLAY_DATA.demoList[1] = but.demo1;
         APP_REPLAY_DATA.demoList[2] = but.demo2;
         APP_REPLAY_DATA.demoList[3] = but.demo3;
         APP_REPLAY_DATA.demoList[4] = but.demo4;
      }
      else
      {
         APP_REPLAY_DATA.ep = but.ep;
         APP_REPLAY_DATA.lev = but.lev;
         APP_REPLAY_DATA.demo = but.demo;
         APP_REPLAY_DATA.score = but.score;
      }
      App_StartLoadingNextHighscoreReplay();
   }
}
function App_StartLoadingNextHighscoreReplay()
{
   gui.HideInGame();
   var menuMC = gui.GetCurrentMC();
   var scoreMC = eval(menuMC + ".scoremenu");
   scoreMC.statusbox.msg.text = "loading level..";
   var ep;
   var lev;
   var str;
   if(APP_REPLAY_DATA.isEpisode)
   {
      ep = APP_REPLAY_DATA.ep;
      lev = APP_REPLAY_DATA.lev;
      str = APP_REPLAY_DATA.demoList[lev];
      if(APP_REPLAY_DATA.lev == 0)
      {
         game.InitNewGame(0);
         gui.SetPlayerTime(game.playerMaxTime);
      }
      APP_REPLAY_DATA.lev = (APP_REPLAY_DATA.lev + 1) % 5;
   }
   else
   {
      ep = APP_REPLAY_DATA.ep;
      lev = APP_REPLAY_DATA.lev;
      str = APP_REPLAY_DATA.demo;
      game.InitNewGame(1);
      gui.SetPlayerTime(game.playerMaxTime);
   }
   App_PlayerDeathEvent = App_PlayerDeathEvent_Normal;
   App_LevelPassedEvent = App_PlayerDeathEvent_Normal;
   game.InitNewLevel();
   game.StopDemoPlayback();
   game.LoadDemo(str);
   game.StartDemoPlayback();
   gamedata.LoadEpisodeNum(ep);
   gamedata.curLevel = lev;
   APP_HIGHSCORE_REPLAY_READY = false;
   App_LoadLevel(gamedata.GetCurrentLevelID(),App_HighscoreReady);
   console.Show();
}
function App_HighscoreReady()
{
   var menuMC = gui.GetCurrentMC();
   var scoreMC = eval(menuMC + ".scoremenu");
   scoreMC.statusbox.msg.text += "done.";
   console.Hide();
   SetActiveProcess(App_TickHighscoreMenu);
   APP_HIGHSCORE_REPLAY_READY = true;
   if(!APP_CANCEL_AUTOPLAY)
   {
      App_StartHighscoreReplay();
   }
   if(APP_CURRENTHIGHSCOREMODE == APP_HIGHSCOREMODE_PLAYING)
   {
      gui.ShowInGame();
      gui.DrawLevelName(gamedata.GetCurrentLevelName());
   }
   else if(APP_CURRENTHIGHSCOREMODE == APP_HIGHSCOREMODE_MENU)
   {
      gui.HideInGame();
   }
}
function App_StartHighscoreReplay()
{
   game.StartDemoPlayback();
   App_ResetGameTime();
   App_ShowHighscoreReplay();
}
function App_TickHighscoreReplay()
{
   if(game.GetDemoTickCount() - game.GetTime() < -80)
   {
      return false;
   }
   if(game.GetTime() < game.GetDemoTickCount())
   {
      App_UpdateGame_Demo(true);
   }
   else
   {
      App_UpdateGame_Demo(false);
   }
   game.DrawPlayerTime();
   return true;
}
function App_HighscoreMenu_SubmitClicked(but)
{
   var menuMC = gui.GetCurrentMC();
   var scoreMC = eval(menuMC + ".scoremenu");
   scoreMC.statusbox.msg.text = "submitting score(s)..";
   var epnum = -1;
   var escore = -1;
   var epdemo0 = "";
   var epdemo1 = "";
   var epdemo2 = "";
   var epdemo3 = "";
   var epdemo4 = "";
   var levscore0 = -1;
   var levscore1 = -1;
   var levscore2 = -1;
   var levscore3 = -1;
   var levscore4 = -1;
   var levdemo0 = "";
   var levdemo1 = "";
   var levdemo2 = "";
   var levdemo3 = "";
   var levdemo4 = "";
   var isGood = false;
   if(APP_PERSBEST_ONLINE.ep != null)
   {
      isGood = true;
      var temp = APP_PERSBEST_ONLINE.ep;
      escore = temp.score;
      epdemo0 = temp.demo0;
      epdemo1 = temp.demo1;
      epdemo2 = temp.demo2;
      epdemo3 = temp.demo3;
      epdemo4 = temp.demo4;
   }
   if(APP_PERSBEST_ONLINE.lev0 != null)
   {
      isGood = true;
      var temp = APP_PERSBEST_ONLINE.lev0;
      levscore0 = temp.score;
      levdemo0 = temp.demo;
   }
   if(APP_PERSBEST_ONLINE.lev1 != null)
   {
      isGood = true;
      var temp = APP_PERSBEST_ONLINE.lev1;
      levscore1 = temp.score;
      levdemo1 = temp.demo;
   }
   if(APP_PERSBEST_ONLINE.lev2 != null)
   {
      isGood = true;
      var temp = APP_PERSBEST_ONLINE.lev2;
      levscore2 = temp.score;
      levdemo2 = temp.demo;
   }
   if(APP_PERSBEST_ONLINE.lev3 != null)
   {
      isGood = true;
      var temp = APP_PERSBEST_ONLINE.lev3;
      levscore3 = temp.score;
      levdemo3 = temp.demo;
   }
   if(APP_PERSBEST_ONLINE.lev4 != null)
   {
      isGood = true;
      var temp = APP_PERSBEST_ONLINE.lev4;
      levscore4 = temp.score;
      levdemo4 = temp.demo;
   }
   if(isGood)
   {
      epnum = APP_HIGHSCORE_ONLINE_EP;
      onlineclient.SubmitPersBestDemos(epnum,escore,epdemo0,epdemo1,epdemo2,epdemo3,epdemo4,levscore0,levdemo0,levscore1,levdemo1,levscore2,levdemo2,levscore3,levdemo3,levscore4,levdemo4,App_NotifyPersbestReceived);
   }
}
function App_HighscoreMenu_ContinueSubmit()
{
   if(APP_SUBMIT_LEV < 5)
   {
      var menuMC = gui.GetCurrentMC();
      var scoreMC = eval(menuMC + ".scoremenu");
      scoreMC.statusbox.msg.text += "..";
      var temp = APP_PERSBEST_ONLINE["lev" + APP_SUBMIT_LEV];
      if(temp == null)
      {
         APP_SUBMIT_LEV++;
         App_HighscoreMenu_ContinueSubmit();
         return undefined;
      }
      onlineclient.SubmitLevelDemo(temp.userN,temp.userP,temp.epNum,temp.levNum,temp.score,temp.demo,App_HighscoreMenu_ContinueSubmit);
      APP_PERSBEST_ONLINE["lev" + APP_SUBMIT_LEV] = null;
      APP_SUBMIT_LEV++;
   }
   else
   {
      var menuMC = gui.GetCurrentMC();
      var scoreMC = eval(menuMC + ".scoremenu");
      scoreMC.statusbox.msg.text += "done.\n";
      App_NotifyPersbestReceived();
   }
}
function App_NotifyPersbestReceived(isValid)
{
   App_HighscoreEpisodeButtonClicked(APP_HIGHSCORE_CUR_SELECTED,true);
}
function App_ReceiveOnlineDemo_Episode(isValid)
{
   var menuMC = gui.GetCurrentMC();
   var scoreMC = eval(menuMC + ".scoremenu");
   scoreMC.statusbox.msg.text += "done.\n";
   var qryData = onlineclient.GetLoadedData();
   if(isValid)
   {
      APP_REPLAY_DATA.isEpisode = true;
      APP_REPLAY_DATA.ep = qryData.epnum;
      APP_REPLAY_DATA.lev = 0;
      APP_REPLAY_DATA.demoList = new Array();
      APP_REPLAY_DATA.score = qryData.score;
      APP_REPLAY_DATA.demoList[0] = qryData.demo0;
      APP_REPLAY_DATA.demoList[1] = qryData.demo1;
      APP_REPLAY_DATA.demoList[2] = qryData.demo2;
      APP_REPLAY_DATA.demoList[3] = qryData.demo3;
      APP_REPLAY_DATA.demoList[4] = qryData.demo4;
      App_StartLoadingNextHighscoreReplay();
   }
   else
   {
      var stat = qryData.stat;
   }
}
function App_ReceiveOnlineDemo_Level(isValid)
{
   var menuMC = gui.GetCurrentMC();
   var scoreMC = eval(menuMC + ".scoremenu");
   scoreMC.statusbox.msg.text += "done.\n";
   var qryData = onlineclient.GetLoadedData();
   if(isValid)
   {
      APP_REPLAY_DATA.isEpisode = false;
      APP_REPLAY_DATA.ep = qryData.epnum;
      APP_REPLAY_DATA.lev = qryData.levnum;
      APP_REPLAY_DATA.demo = qryData.demo;
      APP_REPLAY_DATA.score = qryData.score;
      App_StartLoadingNextHighscoreReplay();
   }
   else
   {
      var stat = qryData.stat;
   }
}
function App_ReceiveOnlineRecords(isLoaded)
{
   var menuMC = gui.GetCurrentMC();
   var scoreMC = eval(menuMC + ".scoremenu");
   var qryData = onlineclient.GetLoadedData();
   if(isLoaded)
   {
      var i = 0;
      while(i < 20)
      {
         var recordMC = eval(scoreMC + ".recPanel.epPanel.record_" + i);
         var score = qryData["escore" + i];
         var username = qryData["ename" + i];
         var pkey = qryData["epkey" + i];
         recordMC.isOnline = true;
         recordMC.isEpisode = true;
         recordMC.isLoaded = true;
         recordMC.scorebox.text = gui.FormatTime(score);
         recordMC.score = score;
         recordMC.username.text = username;
         recordMC.pkey = pkey;
         recordMC.epnum = APP_HIGHSCORE_ONLINE_EP;
         recordMC.gfx._visible = true;
         recordMC.enabled = true;
         recordMC.onRelease = function()
         {
            _root.App_HighscoreRecordButtonClicked(this,true);
         };
         i++;
      }
      var j = 0;
      while(j < 5)
      {
         var recName = ".recPanel.lev" + j + "Panel.record_";
         var i = 0;
         while(i < 20)
         {
            var recordMC = eval(scoreMC + recName + i);
            var score = qryData["" + j + "score" + i];
            var username = qryData["" + j + "name" + i];
            var pkey = qryData["" + j + "pkey" + i];
            recordMC.isOnline = true;
            recordMC.isEpisode = false;
            recordMC.isLoaded = true;
            recordMC.scorebox.text = gui.FormatTime(score);
            recordMC.score = score;
            recordMC.username.text = username;
            recordMC.pkey = pkey;
            recordMC.epnum = APP_HIGHSCORE_ONLINE_EP;
            recordMC.levnum = j;
            recordMC.gfx._visible = true;
            recordMC.enabled = true;
            recordMC.onRelease = function()
            {
               _root.App_HighscoreRecordButtonClicked(this,false);
            };
            i++;
         }
         j++;
      }
      scoreMC.statusbox.msg.text += "done.\n";
      scoreMC.statusbox.msg.text += "click a highscore to view replay.";
   }
   else
   {
      var stat = qryData.stat;
   }
}
APP_HIGHSCORE_CUR_SELECTED = null;
APP_HIGHSCORE_REPLAY_READY = false;
APP_CANCEL_AUTOPLAY = false;
APP_HIGHSCOREMODE_PLAYING = 0;
APP_HIGHSCOREMODE_MENU = 1;
APP_CURRENTHIGHSCOREMODE = APP_HIGHSCOREMODE_MENU;
APP_PERSBEST_ONLINE = new Object();
APP_HS_CURRENTLEVEL_TT = -1;
APP_HS_CURRENTEPISODE_TT = -1;
APP_HS_CURRENTLEVEL_TT_CHEATER = true;
APP_SUBMIT_LEV = 0;
APP_HIGHSCORE_ONLINE_EP = 0;
APP_HIGHSCORE_CUR_PANEL = null;
