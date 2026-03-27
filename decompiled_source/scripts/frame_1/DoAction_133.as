function App_Spider_BeginProcessing()
{
   SetActiveProcess(App_Spider_Tick_Processing);
}
function App_Spider_FinishProcessing()
{
}
function App_Spider_DumpLog()
{
   var _loc2_ = new Date();
   APP_SPIDER_LOG = "N spider log: " + _loc2_.toString();
   APP_SPIDER_LOG += "\n\n";
   APP_SPIDER_LOG += "[valid scores]\n";
   APP_SPIDER_LOG += "----[episodes]: " + APP_SPIDER_VALIDLIST_EP.length + "\n";
   var _loc1_;
   while(APP_SPIDER_VALIDLIST_EP.length != 0)
   {
      _loc1_ = APP_SPIDER_VALIDLIST_EP.pop();
      APP_SPIDER_LOG += ":" + _loc1_.pkey + " | " + _loc1_.epnum + " | " + _loc1_.levnum + " | " + _loc1_.score + "\n";
   }
   APP_SPIDER_LOG += "------[levels]: " + APP_SPIDER_VALIDLIST_LEV.length + "\n";
   while(APP_SPIDER_VALIDLIST_LEV.length != 0)
   {
      _loc1_ = APP_SPIDER_VALIDLIST_LEV.pop();
      APP_SPIDER_LOG += ":" + _loc1_.pkey + " | " + _loc1_.epnum + " | " + _loc1_.levnum + " | " + _loc1_.score + "\n";
   }
   APP_SPIDER_LOG += "[corrupt scores]\n";
   APP_SPIDER_LOG += "------[episodes]: " + APP_SPIDER_CORRUPTLIST_EP.length + "\n";
   while(APP_SPIDER_CORRUPTLIST_EP.length != 0)
   {
      _loc1_ = APP_SPIDER_CORRUPTLIST_EP.pop();
      APP_SPIDER_LOG += ":" + _loc1_.pkey + " | " + _loc1_.epnum + " | " + _loc1_.levnum + " | " + _loc1_.score + " | " + _loc1_.badscore + "\n";
   }
   APP_SPIDER_LOG += "--------[levels]: " + APP_SPIDER_CORRUPTLIST_LEV.length + "\n";
   while(APP_SPIDER_CORRUPTLIST_LEV.length != 0)
   {
      _loc1_ = APP_SPIDER_CORRUPTLIST_LEV.pop();
      APP_SPIDER_LOG += ":" + _loc1_.pkey + " | " + _loc1_.epnum + " | " + _loc1_.levnum + " | " + _loc1_.score + " | " + _loc1_.badscore + "\n";
   }
}
function App_Spider_Tick_Processing()
{
}
function App_Spider_ProcessEpisode(isValid)
{
}
function App_Spider_ProcessLevel(isValid)
{
}
function App_Spider_StartTestingEpisode(pkey, epnum, numticks, demo0, demo1, demo2, demo3, demo4)
{
   game.InitNewGame(false);
   APP_SPIDER_PKEY = pkey;
   APP_SPIDER_NUMTICKS = numticks;
   APP_SPIDER_EPDEMO[0] = demo0;
   APP_SPIDER_EPDEMO[1] = demo1;
   APP_SPIDER_EPDEMO[2] = demo2;
   APP_SPIDER_EPDEMO[3] = demo3;
   APP_SPIDER_EPDEMO[4] = demo4;
   APP_SPIDER_ISEPISODE = true;
   APP_SPIDER_EPNUM = epnum;
   APP_SPIDER_LEVNUM = 0;
   game.InitNewGame(false);
   App_Spider_RunTest();
}
function App_Spider_StartTestingLevel(pkey, epnum, levnum, numticks, demo)
{
   APP_SPIDER_PKEY = pkey;
   APP_SPIDER_NUMTICKS = numticks;
   APP_SPIDER_LEVDEMO = demo;
   APP_SPIDER_ISEPISODE = false;
   APP_SPIDER_EPNUM = epnum;
   APP_SPIDER_LEVNUM = levnum;
   game.InitNewGame(true);
   App_Spider_RunTest();
}
function App_LevelPassedEvent_Spider()
{
   if(APP_SPIDER_ISEPISODE)
   {
      APP_SPIDER_LEVNUM++;
      if(APP_SPIDER_LEVNUM < 5)
      {
         App_Spider_RunTest();
         return undefined;
      }
      App_Spider_VerifyResult();
      SetActiveProcess(App_Spider_Tick_Processing);
      return undefined;
   }
   App_Spider_VerifyResult();
   SetActiveProcess(App_Spider_Tick_Processing);
   return undefined;
}
function App_PlayerDeathEvent_Spider()
{
   App_Spider_ResultCorrupt(-1);
}
function App_Spider_VerifyResult()
{
   var _loc1_ = game.GetPlayerTime();
   if(APP_SPIDER_NUMTICKS == _loc1_)
   {
      App_Spider_ResultValid();
   }
   else
   {
      App_Spider_ResultCorrupt(_loc1_);
   }
}
function App_Spider_ResultValid()
{
   var _loc1_ = new Object();
   _loc1_.pkey = APP_SPIDER_PKEY;
   _loc1_.score = APP_SPIDER_NUMTICKS;
   _loc1_.epnum = APP_SPIDER_EPNUM;
   _loc1_.levnum = APP_SPIDER_LEVNUM;
   if(APP_SPIDER_ISEPISODE)
   {
      APP_SPIDER_VALIDLIST_EP.push(_loc1_);
   }
   else
   {
      APP_SPIDER_VALIDLIST_LEV.push(_loc1_);
   }
}
function App_Spider_ResultCorrupt(badTime)
{
   var _loc1_ = new Object();
   _loc1_.pkey = APP_SPIDER_PKEY;
   _loc1_.score = APP_SPIDER_NUMTICKS;
   _loc1_.badscore = badTime;
   _loc1_.epnum = APP_SPIDER_EPNUM;
   _loc1_.levnum = APP_SPIDER_LEVNUM;
   if(APP_SPIDER_ISEPISODE)
   {
      APP_SPIDER_CORRUPTLIST_EP.push(_loc1_);
   }
   else
   {
      APP_SPIDER_CORRUPTLIST_LEV.push(_loc1_);
   }
}
function App_Spider_RunTest()
{
   game.InitNewLevel();
   gamedata.LoadEpisodeNum(APP_SPIDER_EPNUM);
   App_LoadLevel(APP_SPIDER_LEVNUM,App_Spider_PlayGame_Normal);
}
function App_Spider_PlayGame_Normal()
{
   gui.HideAll();
   gui.HideNotify();
   var _loc1_ = new Sound();
   _loc1_.stop();
   _loc1_.setVolume(0);
   game.InitNewLevel();
   game.SetDemoFormat(false);
   game.StopDemoPlayback();
   game.StopRecordingDemo();
   game.InitRetryLevel();
   game.StopDemoPlayback();
   if(APP_SPIDER_ISEPISODE)
   {
      game.LoadDemo(APP_SPIDER_EPDEMO[APP_SPIDER_LEVNUM]);
   }
   else
   {
      game.LoadDemo(APP_SPIDER_LEVDEMO);
   }
   game.StartDemoPlayback();
   App_PlayerDeathEvent = App_PlayerDeathEvent_Spider;
   App_LevelPassedEvent = App_LevelPassedEvent_Spider;
   SetActiveProcess(App_Spider_Tick_RunningGame);
}
function App_Spider_Tick_RunningGame()
{
   App_Spider_UpdateGame();
   if(game.playerCurTime <= 0)
   {
      game.KillPlayer(KILLTYPE_FALL,0,0,player.pos.x,player.pos.y,player);
   }
}
function App_UpdateGame()
{
   var _loc2_ = APP_SPIDER_GAMETIME_t0;
   APP_SPIDER_GAMETIME_t0 = APP_t0;
   var _loc1_ = APP_SPIDER_GAMETIME_t0 - _loc2_ + APP_SPIDER_GAMETIME_REMAINDER;
   var _loc3_ = _loc1_;
   if(2000 < _loc1_)
   {
      _loc1_ = APP_SPIDER_GAMETIME_TICKLEN;
   }
   while(APP_SPIDER_GAMETIME_TICKLEN <= _loc1_)
   {
      _loc1_ -= APP_SPIDER_GAMETIME_TICKLEN;
      game.Tick();
      game.playerCurTime--;
   }
   APP_SPIDER_GAMETIME_REMAINDER = _loc1_;
}
APP_SPIDER_PKEY = -1;
APP_SPIDER_NUMTICKS = -1;
APP_SPIDER_EPDEMO = new Array();
var i = 0;
while(i < 5)
{
   APP_SPIDER_EPDEMO[i] = "";
   i++;
}
APP_SPIDER_ISEPISODE = false;
APP_SPIDER_EPNUM = -1;
APP_SPIDER_LEVNUM = -1;
APP_SPIDER_LOG = "";
APP_SPIDER_VALIDLIST_EP = new Array();
APP_SPIDER_CORRUPTLIST_EP = new Array();
APP_SPIDER_VALIDLIST_LEV = new Array();
APP_SPIDER_CORRUPTLIST_LEV = new Array();
APP_SPIDER_GAMETIME_t0 = 0;
APP_SPIDER_GAMETIME_REMAINDER = 0;
