function NinjaData()
{
   this.curLevel = 0;
   this.curEpisode = 0;
   this.curHelpDemo = HELPDEMO_JUMP1;
   this.helpLevelStr = "";
   this.episodeList = new Array();
   this.levelList = new Array();
   this.menudemoList = new Object();
   this.helpdemoList = new Object();
   this.menudemoTotalNum = 0;
   this.BuildGameData();
   this.menuShuffleList = new Array();
   var _loc2_ = 0;
   while(_loc2_ < this.menudemoTotalNum)
   {
      this.menuShuffleList[_loc2_] = _loc2_;
      _loc2_ = _loc2_ + 1;
   }
   this.curMenuDemo = 0;
   this.ShuffleMenuDemos();
}
NinjaData.prototype.GetBlankMap = function()
{
   return "00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000";
};
NinjaData.prototype.GetFullMap = function()
{
   return "11111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111";
};
NinjaData.prototype.IncrementCurrentLevel = function()
{
   this.curLevel = this.curLevel + 1;
   if(this.levelList.length <= this.curLevel)
   {
      this.curLevel = 0;
      return false;
   }
   return true;
};
NinjaData.prototype.GetCurrentLevelID = function()
{
   return this.curLevel;
};
NinjaData.prototype.GetLevelData = function(id)
{
   if(id < 0 || this.levelList.length <= id)
   {
      return null;
   }
   return this.levelList[id].levStr;
};
NinjaData.prototype.GetCurrentLevelName = function()
{
   var _loc2_ = "Episode " + this.curEpisode + " Level " + this.curLevel + ": " + this.levelList[this.curLevel].levname;
   return _loc2_;
};
NinjaData.prototype.LoadEpisode = function(code)
{
   var _loc2_ = 0;
   while(_loc2_ < this.episodeList.length)
   {
      if(this.episodeList[_loc2_].code == code)
      {
         this.curLevel = 0;
         this.curEpisode = _loc2_;
         this.levelList = this.episodeList[_loc2_].levelList;
         return true;
      }
      _loc2_ = _loc2_ + 1;
   }
   this.ResetEpisode();
   return false;
};
NinjaData.prototype.LoadEpisodeNum = function(num)
{
   if(this.episodeList[num] != null)
   {
      this.curLevel = 0;
      this.curEpisode = num;
      this.levelList = this.episodeList[num].levelList;
      return true;
   }
   this.ResetEpisode();
   return false;
};
NinjaData.prototype.ResetEpisode = function()
{
   this.curEpisode = 0;
   this.curLevel = 0;
   this.levelList = this.episodeList[this.curEpisode].levelList;
};
NinjaData.prototype.GetNextEpisodeNum = function()
{
   if(this.curEpisode == EPISODE_FINAL0)
   {
      return -1;
   }
   if(this.curEpisode == EPISODE_FINAL1)
   {
      return -1;
   }
   if(this.curEpisode == EPISODE_FINAL2)
   {
      return -1;
   }
   if(this.curEpisode == EPISODE_FINAL3)
   {
      return -1;
   }
   if(this.curEpisode == EPISODE_FINAL4)
   {
      return -1;
   }
   if(this.curEpisode == EPISODE_FINAL5)
   {
      return -1;
   }
   if(this.curEpisode == EPISODE_FINAL6)
   {
      return -1;
   }
   if(this.curEpisode == EPISODE_FINAL7)
   {
      return -1;
   }
   if(this.curEpisode == EPISODE_FINAL8)
   {
      return -1;
   }
   if(this.curEpisode == EPISODE_FINAL9)
   {
      return -1;
   }
   this.curEpisode += 1;
   return this.curEpisode;
};
NinjaData.prototype.GetHelpLevelData = function()
{
   return this.helpLevelStr;
};
NinjaData.prototype.GetCurrentHelpDemo = function()
{
   return this.curHelpDemo;
};
NinjaData.prototype.SetCurrentHelpDemo = function(demoID)
{
   if(this.helpdemoList[demoID] != null)
   {
      this.curHelpDemo = demoID;
      this.curHelpDemoReel = 0;
   }
};
NinjaData.prototype.GetHelpDemoObjects = function()
{
   return this.helpdemoList[this.curHelpDemo].objStr;
};
NinjaData.prototype.GetCurrentHelpDemoData = function()
{
   return this.helpdemoList[this.curHelpDemo].demoList[this.curHelpDemoReel];
};
NinjaData.prototype.IncrementHelpDemoReel = function()
{
   this.curHelpDemoReel = (1 + this.curHelpDemoReel) % this.helpdemoList[this.curHelpDemo].demoList.length;
};
NinjaData.prototype.GetCurrentMenuDemoID = function()
{
   return this.menuShuffleList[this.curMenuDemo];
};
NinjaData.prototype.IncrementCurrentMenuDemo = function()
{
   this.curMenuDemo = this.curMenuDemo + 1;
   if(this.menudemoTotalNum <= this.curMenuDemo)
   {
      this.curMenuDemo = 0;
      this.ShuffleMenuDemos();
   }
};
NinjaData.prototype.ShuffleMenuDemos = function()
{
   var _loc5_ = this.menudemoTotalNum;
   var _loc2_ = 0;
   var _loc3_;
   var _loc4_;
   while(_loc2_ < _loc5_)
   {
      _loc3_ = Math.floor(Math.random() * _loc5_);
      _loc4_ = this.menuShuffleList[_loc2_];
      this.menuShuffleList[_loc2_] = this.menuShuffleList[_loc3_];
      this.menuShuffleList[_loc3_] = _loc4_;
      _loc2_ = _loc2_ + 1;
   }
};
NinjaData.prototype.GetMenuDemoLevel = function(demoID)
{
   var _loc2_ = this.menudemoList[demoID];
   if(_loc2_ != null)
   {
      return this.episodeList[_loc2_.epID].levelList[_loc2_.levNum].levStr;
   }
   return null;
};
NinjaData.prototype.GetMenuDemoData = function(demoID)
{
   var _loc2_ = this.menudemoList[demoID];
   if(_loc2_ != null)
   {
      return _loc2_.demoStr;
   }
   return null;
};
