function App_StartCustomMenu(reload)
{
   gui.HideInGame();
   gui.Display(GUI_CUSTOMMENU);
   SetActiveProcess(App_TickCustomMenu);
   var menuMC = gui.GetCurrentMC();
   var container = eval(menuMC + ".custommenu.container");
   container._visible = true;
   var butpanel = eval(menuMC + ".custommenu.container" + ".butpanel");
   var busymc = eval(menuMC + ".custommenu.container" + ".busyMC");
   var inbox = eval(menuMC + ".custommenu.container" + ".replaybox");
   var menutoggle = eval(menuMC + ".custommenu" + ".menutoggle");
   menutoggle._visible = false;
   var s = new Sound();
   s.stop();
   if(reload)
   {
      butpanel._visible = false;
      busymc._visible = true;
      busymc.gotoAndPlay(1);
      inbox.text = "";
      APP_CUSTOM_LOADDATA = true;
   }
   else
   {
      APP_CUSTOM_LOADDATA = false;
      APP_CUSTOM_FINISHEDPARSING = true;
      APP_CUSTOM_READYTOPARSE = true;
      busymc._visible = false;
      busymc.gotoAndStop(1);
      butpanel._visible = true;
      inbox.text = APP_CUSTOM_REPLAY;
   }
}
function App_TickCustomMenu()
{
   var _loc1_;
   if(APP_CUSTOM_LOADDATA)
   {
      APP_CUSTOM_LOADDATA = false;
      App_Custom_LoadLevelList();
   }
   else if(!APP_CUSTOM_FINISHEDPARSING && APP_CUSTOM_READYTOPARSE)
   {
      App_ContinueParseUserLevels();
   }
   else if(APP_CUSTOM_RUNNINGREPLAY)
   {
      if(!App_TickCustomReplay())
      {
         _loc1_ = new Sound();
         _loc1_.stop();
         game.StopDemoPlayback();
         App_Custom_LoadReplay();
      }
   }
}
function App_StartParseUserLevels(str)
{
   APP_CUSTOM_RECORDS = new Array();
   APP_CUSTOM_RAWROWDATA = str.split("$");
   APP_CUSTOM_CURRENTPARSEROW = 1;
   APP_CUSTOM_READYTOPARSE = true;
}
function App_ContinueParseUserLevels()
{
   var _loc7_ = APP_CUSTOM_RAWROWDATA;
   var _loc10_ = APP_CUSTOM_CURRENTPARSEROW;
   var _loc3_ = APP_CUSTOM_RAWROWDATA[APP_CUSTOM_CURRENTPARSEROW];
   var _loc1_ = _loc3_.split("#");
   var _loc5_ = userdata.GetPersBest_Custom(_loc1_[3]);
   var _loc4_ = {levname:_loc1_[0],authname:_loc1_[1],desc:_loc1_[2],levdata:_loc1_[3],pbest:_loc5_};
   APP_CUSTOM_RECORDS.push(_loc4_);
   APP_CUSTOM_CURRENTPARSEROW++;
   var _loc2_;
   if(APP_CUSTOM_RAWROWDATA.length <= APP_CUSTOM_CURRENTPARSEROW)
   {
      _loc2_ = new Array();
      _loc2_[0] = "desc";
      _loc2_[1] = "authname";
      _loc2_[2] = "levname";
      APP_CUSTOM_RECORDS.sortOn(_loc2_,Array.CASEINSENSITIVE);
      APP_CUSTOM_SORT_2 = true;
      App_FinishParseUserLevels();
   }
}
function App_FinishParseUserLevels()
{
   APP_CUSTOM_TOPBUT = 0;
   var menuMC = gui.GetCurrentMC();
   var butpanel = eval(menuMC + ".custommenu.container" + ".butpanel");
   butpanel._visible = true;
   butpanel.scroller._y = 0;
   var numrecs = APP_CUSTOM_RECORDS.length;
   var i = 0;
   while(i < APP_CUSTOM_NUMBUTS)
   {
      var but = eval(menuMC + ".custommenu.container.butpanel.scroller.but" + i);
      but._y = i * APP_CUSTOM_BUTSIZE;
      but.butnum = i;
      var pbut = eval(menuMC + ".custommenu.container.butpanel.scroller.pbut" + i);
      pbut._y = i * APP_CUSTOM_BUTSIZE;
      pbut.butnum = i;
      if(numrecs <= i)
      {
         but._visible = false;
         pbut._visible = false;
      }
      else
      {
         var rec = APP_CUSTOM_RECORDS[i];
         but._visible = true;
         but.levname.text = rec.levname;
         but.authname.text = rec.authname;
         but.desc.text = rec.desc;
         but.recnum = i;
         but.levnum.text = "" + but.recnum;
         if(rec.pbest == null)
         {
            pbut._visible = false;
         }
         else
         {
            pbut._visible = true;
            pbut.scorebox.text = gui.FormatTime(rec.pbest.score);
            pbut.demo = rec.pbest.demo;
            pbut.recnum = i;
         }
      }
      i++;
   }
   var busymc = eval(menuMC + ".custommenu.container" + ".busyMC");
   busymc._visible = false;
   busymc.gotoAndStop(1);
   APP_CUSTOM_FINISHEDPARSING = true;
}
function App_Custom_SortButtonPressed(num)
{
   var _loc1_;
   if(APP_CUSTOM_FINISHEDPARSING)
   {
      if(num == 0)
      {
         if(APP_CUSTOM_SORT_0)
         {
            APP_CUSTOM_RECORDS.sortOn("levname",Array.CASEINSENSITIVE | Array.DESCENDING);
            APP_CUSTOM_SORT_0 = false;
         }
         else
         {
            APP_CUSTOM_RECORDS.sortOn("levname",Array.CASEINSENSITIVE);
            APP_CUSTOM_SORT_0 = true;
         }
         APP_CUSTOM_SORT_2 = false;
         APP_CUSTOM_SORT_1 = false;
         App_FinishParseUserLevels();
      }
      else if(num == 1)
      {
         _loc1_ = new Array();
         _loc1_[0] = "authname";
         _loc1_[1] = "desc";
         _loc1_[2] = "levname";
         if(APP_CUSTOM_SORT_1)
         {
            APP_CUSTOM_RECORDS.sortOn(_loc1_,Array.CASEINSENSITIVE | Array.DESCENDING);
            APP_CUSTOM_SORT_1 = false;
         }
         else
         {
            APP_CUSTOM_RECORDS.sortOn(_loc1_,Array.CASEINSENSITIVE);
            APP_CUSTOM_SORT_1 = true;
         }
         APP_CUSTOM_SORT_2 = false;
         APP_CUSTOM_SORT_0 = false;
         App_FinishParseUserLevels();
      }
      else if(num == 2)
      {
         _loc1_ = new Array();
         _loc1_[0] = "desc";
         _loc1_[1] = "authname";
         _loc1_[2] = "levname";
         if(APP_CUSTOM_SORT_2)
         {
            APP_CUSTOM_RECORDS.sortOn(_loc1_,Array.CASEINSENSITIVE | Array.DESCENDING);
            APP_CUSTOM_SORT_2 = false;
         }
         else
         {
            APP_CUSTOM_RECORDS.sortOn(_loc1_,Array.CASEINSENSITIVE);
            APP_CUSTOM_SORT_2 = true;
         }
         APP_CUSTOM_SORT_1 = false;
         APP_CUSTOM_SORT_0 = false;
         App_FinishParseUserLevels();
      }
   }
}
function App_Custom_LoadLevelList()
{
   var menuMC = gui.GetCurrentMC();
   var butpanel = eval(menuMC + ".custommenu.container" + ".butpanel");
   var busymc = eval(menuMC + ".custommenu.container" + ".busyMC");
   busymc._visible = true;
   busymc.gotoAndPlay(1);
   butpanel._visible = false;
   butpanel.scroller._y = 0;
   APP_CUSTOM_FINISHEDPARSING = false;
   APP_CUSTOM_READYTOPARSE = false;
   APP_CUSTOM_LOADER = new LoadVars();
   APP_CUSTOM_LOADER.onLoad = function()
   {
      App_StartParseUserLevels(this.userdata);
   };
   APP_CUSTOM_LOADER.load("userlevels.txt");
}
function App_Custom_RefreshButtonPressed()
{
   APP_CUSTOM_LOADDATA = true;
}
function App_Custom_LevelButtonPressed(but)
{
   var _loc2_ = but.recnum;
   APP_CUSTOM_SELECTEDRECORD = _loc2_;
   APP_CUSTOM_SELECTEDBUTTON = but.butnum;
   var _loc1_ = APP_CUSTOM_RECORDS[_loc2_];
   APP_IS_PRACTISE = userdata.GetPractiseMode();
   App_StartNewGame_Custom(_loc1_.levname,_loc1_.authname,_loc1_.levdata,_loc1_.desc);
}
function App_Custom_RefreshRecordPBest(rec)
{
   var _loc1_ = userdata.GetPersBest_Custom(rec.levdata);
   rec.pbest = _loc1_;
}
function App_Custom_RefreshButtonPBest(rec, bnum)
{
   var menuMC = gui.GetCurrentMC();
   var pbut = eval(menuMC + ".custommenu.container.butpanel.scroller.pbut" + bnum);
   var but = eval(menuMC + ".custommenu.container.butpanel.scroller.but" + bnum);
   if(rec.pbest == null)
   {
      pbut._visible = false;
   }
   else
   {
      pbut._visible = true;
      pbut.scorebox.text = gui.FormatTime(rec.pbest.score);
      pbut.demo = rec.pbest.demo;
      pbut.recnum = but.recnum;
   }
}
function App_Custom_ScrollButtonPressed(dir)
{
   if(dir == -1)
   {
      App_Custom_ScrollUp();
   }
   else if(dir == 1)
   {
      App_Custom_ScrollDown();
   }
}
function App_Custom_ScrollUp()
{
   if(APP_CUSTOM_RECORDS.length < APP_CUSTOM_NUMBUTS || !APP_CUSTOM_FINISHEDPARSING)
   {
      return undefined;
   }
   var menuMC = gui.GetCurrentMC();
   var bottom = (APP_CUSTOM_TOPBUT + APP_CUSTOM_NUMBUTS - 1) % APP_CUSTOM_NUMBUTS;
   var topbut = eval(menuMC + ".custommenu.container.butpanel.scroller.but" + APP_CUSTOM_TOPBUT);
   var botbut = eval(menuMC + ".custommenu.container.butpanel.scroller.but" + bottom);
   var botbutP = eval(menuMC + ".custommenu.container.butpanel.scroller.pbut" + bottom);
   var newindex = (topbut.recnum - 1 + APP_CUSTOM_RECORDS.length) % APP_CUSTOM_RECORDS.length;
   if(0 <= newindex && newindex < APP_CUSTOM_RECORDS.length)
   {
      var scroller = eval(menuMC + ".custommenu.container.butpanel.scroller");
      scroller._y += APP_CUSTOM_BUTSIZE;
      botbut._y -= APP_CUSTOM_BUTSIZE * APP_CUSTOM_NUMBUTS;
      botbutP._y -= APP_CUSTOM_BUTSIZE * APP_CUSTOM_NUMBUTS;
      var rec = APP_CUSTOM_RECORDS[newindex];
      botbut._visible = true;
      botbut.levname.text = rec.levname;
      botbut.authname.text = rec.authname;
      botbut.desc.text = rec.desc;
      botbut.recnum = newindex;
      botbut.levnum.text = "" + botbut.recnum;
      botbutP.recnum = newindex;
      if(rec.pbest == null)
      {
         botbutP._visible = false;
      }
      else
      {
         botbutP._visible = true;
         botbutP.scorebox.text = gui.FormatTime(rec.pbest.score);
         botbutP.demo = rec.pbest.demo;
      }
      APP_CUSTOM_TOPBUT = bottom;
   }
}
function App_Custom_ScrollDown()
{
   if(APP_CUSTOM_RECORDS.length < APP_CUSTOM_NUMBUTS || !APP_CUSTOM_FINISHEDPARSING)
   {
      return undefined;
   }
   var menuMC = gui.GetCurrentMC();
   var top = (APP_CUSTOM_TOPBUT + 1) % APP_CUSTOM_NUMBUTS;
   var topbut = eval(menuMC + ".custommenu.container.butpanel.scroller.but" + APP_CUSTOM_TOPBUT);
   var topbutP = eval(menuMC + ".custommenu.container.butpanel.scroller.pbut" + APP_CUSTOM_TOPBUT);
   var newindex = (topbut.recnum + APP_CUSTOM_NUMBUTS) % APP_CUSTOM_RECORDS.length;
   if(0 <= newindex && newindex < APP_CUSTOM_RECORDS.length)
   {
      var scroller = eval(menuMC + ".custommenu.container.butpanel.scroller");
      scroller._y -= APP_CUSTOM_BUTSIZE;
      topbut._y += APP_CUSTOM_BUTSIZE * APP_CUSTOM_NUMBUTS;
      topbutP._y += APP_CUSTOM_BUTSIZE * APP_CUSTOM_NUMBUTS;
      var rec = APP_CUSTOM_RECORDS[newindex];
      topbut._visible = true;
      topbut.levname.text = rec.levname;
      topbut.authname.text = rec.authname;
      topbut.desc.text = rec.desc;
      topbut.recnum = newindex;
      topbut.levnum.text = "" + topbut.recnum;
      topbutP.recnum = newindex;
      if(rec.pbest == null)
      {
         topbutP._visible = false;
      }
      else
      {
         topbutP._visible = true;
         topbutP.scorebox.text = gui.FormatTime(rec.pbest.score);
         topbutP.demo = rec.pbest.demo;
      }
      APP_CUSTOM_TOPBUT = top;
   }
}
function App_Custom_MenuTogglePressed()
{
   App_StopCustomReplay();
}
function App_Custom_ReplayButtonPressed()
{
   var menuMC = gui.GetCurrentMC();
   var inbox = eval(menuMC + ".custommenu.container" + ".replaybox");
   var str = inbox.text;
   if(str != "")
   {
      if(str.substr(0,1) == "$")
      {
         App_Custom_StartLoadingReplay(str);
      }
   }
}
function App_Custom_PBestButtonClicked(but)
{
   var menuMC = gui.GetCurrentMC();
   var inbox = eval(menuMC + ".custommenu.container" + ".replaybox");
   var recbut = eval(menuMC + ".custommenu.container.butpanel.scroller.but" + bnum);
   var recnum = but.recnum;
   var rec = APP_CUSTOM_RECORDS[recnum];
   if(rec.pbest != null)
   {
      var str = "$" + rec.levname + "#" + rec.authname + "#" + rec.desc + "#" + rec.levdata + "#" + rec.pbest.demo;
      inbox.text = str;
      App_Custom_StartLoadingReplay(str);
   }
}
function App_Custom_StartLoadingReplay(str)
{
   var _loc2_ = str.split("$");
   var _loc1_ = _loc2_[1].split("#");
   APP_CUSTOM_LEVELNAME = _loc1_[0];
   APP_CUSTOM_AUTHORNAME = _loc1_[1];
   APP_CUSTOM_DESC = _loc1_[2];
   APP_CUSTOM_LEVELDATA = _loc1_[3];
   APP_CUSTOM_REPLAY_RAWDATA = _loc1_[4];
   APP_CUSTOM_REPLAY = str;
   App_Custom_LoadReplay();
}
function App_Custom_LoadReplay()
{
   APP_CUSTOM_RUNNINGREPLAY = true;
   gui.HideInGame();
   game.InitNewGame(2);
   App_PlayerDeathEvent = App_PlayerDeathEvent_Normal;
   App_LevelPassedEvent = App_PlayerDeathEvent_Normal;
   game.InitNewLevel();
   game.StopDemoPlayback();
   game.LoadDemo(APP_CUSTOM_REPLAY_RAWDATA);
   game.StartDemoPlayback();
   gui.Display(GUI_LOADINGLEVEL);
   App_LoadLevel_Raw(APP_CUSTOM_LEVELDATA,App_StartCustomReplay);
   console.Show();
}
function App_StopCustomReplay()
{
   App_StartCustomMenu(false);
   APP_CUSTOM_RUNNINGREPLAY = false;
}
function App_StartCustomReplay()
{
   console.Hide();
   game.StartDemoPlayback();
   App_ResetGameTime();
   gui.Display(GUI_CUSTOMMENU);
   gui.ShowInGame();
   var str = APP_CUSTOM_LEVELNAME + "  ( by " + APP_CUSTOM_AUTHORNAME + " )";
   gui.DrawLevelName(str);
   var menuMC = gui.GetCurrentMC();
   var container = eval(menuMC + ".custommenu.container");
   container._visible = false;
   var menutoggle = eval(menuMC + ".custommenu" + ".menutoggle");
   menutoggle._visible = true;
   var s = new Sound();
   s.setVolume(Math.round(userdata.GetVol()));
   SetActiveProcess(App_TickCustomMenu);
}
function App_TickCustomReplay()
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
APP_CUSTOM_SORT_0 = false;
APP_CUSTOM_SORT_1 = false;
APP_CUSTOM_SORT_2 = false;
APP_CUSTOM_NUMBUTS = 16;
APP_CUSTOM_TOPBUT = 0;
APP_CUSTOM_BUTSIZE = 24;
APP_CUSTOM_SELECTEDRECORD = 0;
APP_CUSTOM_SELECTEDBUTTON = 0;
APP_CUSTOM_LOADDATA = false;
APP_CUSTOM_READYTOPARSE = false;
APP_CUSTOM_FINISHEDPARSING = false;
APP_CUSTOM_LOADER = null;
APP_CUSTOM_CURRENTPARSEROW = 0;
APP_CUSTOM_RAWROWDATA = null;
APP_CUSTOM_RECORDS = null;
