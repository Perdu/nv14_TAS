function NinjaOnlineClient()
{
   this.lvars = new LoadVars();
   this.currentQnum = 0;
   _root.ONLINECLIENT_CALLBACK = null;
}
ONLINECLIENT_CALLBACK = null;
NinjaOnlineClient.prototype.GetLoadedData = function()
{
   return this.loadedVars;
};
NinjaOnlineClient.prototype.ClearCallback = function()
{
   _root.ONLINECLIENT_CALLBACK = null;
};
NinjaOnlineClient.prototype.InitQuery = function(callback)
{
   this.lvars = new LoadVars();
   this.currentQnum = (this.currentQnum + 1) % 100000;
   this.loadedVars = new LoadVars();
   this.loadedVars.qnum = this.currentQnum;
   this.loadedVars.onLoad = function(success)
   {
      if(this.qnum == _root.onlineclient.currentQnum)
      {
         _root.ONLINECLIENT_CALLBACK(success);
      }
   };
   _root.ONLINECLIENT_CALLBACK = callback;
};
NinjaOnlineClient.prototype.RunQuery = function(callback, qryName)
{
   var _loc3_ = userdata.GetOnlinePath();
   var _loc2_ = _loc3_ + qryName;
   this.lvars.sendAndLoad(_loc2_,this.loadedVars,POST);
};
NinjaOnlineClient.prototype.QueryTopRecords = function(epNum, callback)
{
   var _loc2_ = "get_topscores_query.php";
   this.InitQuery(callback);
   this.lvars.episode_number = epNum;
   this.RunQuery(callback,_loc2_);
};
NinjaOnlineClient.prototype.QueryEpisodeDemo = function(pkey, callback)
{
   var _loc2_ = "get_ep_demo.php";
   this.InitQuery(callback);
   this.lvars.pk = pkey;
   this.RunQuery(callback,_loc2_);
};
NinjaOnlineClient.prototype.QueryLevelDemo = function(pkey, callback)
{
   var _loc2_ = "get_lv_demo.php";
   this.InitQuery(callback);
   this.lvars.pk = pkey;
   this.RunQuery(callback,_loc2_);
};
NinjaOnlineClient.prototype.SubmitEpisodeDemo = function(epnum, score, demo0, demo1, demo2, demo3, demo4, callback)
{
   var _loc2_ = "add_new_ep_highscore.php";
   this.InitQuery(callback);
   if(userdata.IsUserAnon())
   {
      this.lvars.username = "guy_incognito";
      this.lvars.pword = "random123";
   }
   else
   {
      this.lvars.username = userdata.GetUserName();
      this.lvars.pword = userdata.GetUserPass();
   }
   this.lvars.episode_number = epnum;
   this.lvars.score = score;
   this.lvars.demo0 = demo0;
   this.lvars.demo1 = demo1;
   this.lvars.demo2 = demo2;
   this.lvars.demo3 = demo3;
   this.lvars.demo4 = demo4;
   this.RunQuery(callback,_loc2_);
};
NinjaOnlineClient.prototype.SubmitLevelDemo = function(epnum, levnum, score, demo, callback)
{
   var _loc2_ = "add_new_lv_highscore.php";
   this.InitQuery(callback);
   if(userdata.IsUserAnon())
   {
      this.lvars.username = "guy_incognito";
      this.lvars.pword = "random123";
   }
   else
   {
      this.lvars.username = userdata.GetUserName();
      this.lvars.pword = userdata.GetUserPass();
   }
   this.lvars.episode_number = epnum;
   this.lvars.level_number = levnum;
   this.lvars.score = score;
   this.lvars.demo = demo;
   this.RunQuery(callback,_loc2_);
};
NinjaOnlineClient.prototype.SubmitEpisodeAndLevelDemo = function(epnum, levnum, epscore, levscore, levDemo, demo0, demo1, demo2, demo3, demo4, callback)
{
   var _loc2_ = "add_new_eplv_highscores.php";
   this.InitQuery(callback);
   if(userdata.IsUserAnon())
   {
      this.lvars.username = "guy_incognito";
      this.lvars.pword = "random123";
   }
   else
   {
      this.lvars.username = userdata.GetUserName();
      this.lvars.pword = userdata.GetUserPass();
   }
   this.lvars.episode_number = epnum;
   this.lvars.level_number = levnum;
   this.lvars.escore = epscore;
   this.lvars.lscore = levscore;
   this.lvars.demo = levDemo;
   this.lvars.demo0 = demo0;
   this.lvars.demo1 = demo1;
   this.lvars.demo2 = demo2;
   this.lvars.demo3 = demo3;
   this.lvars.demo4 = demo4;
   this.RunQuery(callback,_loc2_);
};
NinjaOnlineClient.prototype.SubmitPersBestDemos = function(epnum, epscore, demo0e, demo1e, demo2e, demo3e, demo4e, lev0score, demo0, lev1score, demo1, lev2score, demo2, lev3score, demo3, lev4score, demo4, callback)
{
   var _loc2_ = "add_new_pb_highscores.php";
   this.InitQuery(callback);
   if(userdata.IsUserAnon())
   {
      this.lvars.username = "guy_incognito";
      this.lvars.pword = "random123";
   }
   else
   {
      this.lvars.username = userdata.GetUserName();
      this.lvars.pword = userdata.GetUserPass();
   }
   this.lvars.episode_number = epnum;
   this.lvars.escore = epscore;
   this.lvars.demo0e = demo0e;
   this.lvars.demo1e = demo1e;
   this.lvars.demo2e = demo2e;
   this.lvars.demo3e = demo3e;
   this.lvars.demo4e = demo4e;
   this.lvars.lscore0 = lev0score;
   this.lvars.demo0l = demo0;
   this.lvars.lscore1 = lev1score;
   this.lvars.demo1l = demo1;
   this.lvars.lscore2 = lev2score;
   this.lvars.demo2l = demo2;
   this.lvars.lscore3 = lev3score;
   this.lvars.demo3l = demo3;
   this.lvars.lscore4 = lev4score;
   this.lvars.demo4l = demo4;
   this.RunQuery(callback,_loc2_);
};
NinjaOnlineClient.prototype.QueryOnlineGoal_Episode = function(epNum, callback)
{
   var _loc2_ = "ep_lowestscore_query14.php";
   this.InitQuery(callback);
   this.lvars.episode_number = epNum;
   if(userdata.IsUserAnon())
   {
      this.lvars.name = "guy_incognito";
      this.lvars.pword = "random123";
   }
   else
   {
      this.lvars.name = userdata.GetUserName();
      this.lvars.pword = userdata.GetUserPass();
   }
   this.RunQuery(callback,_loc2_);
};
NinjaOnlineClient.prototype.QueryOnlineGoal_Level = function(epNum, levNum, callback)
{
   var _loc2_ = "lv_lowestscore_query14.php";
   this.InitQuery(callback);
   this.lvars.episode_number = epNum;
   this.lvars.level_number = levNum;
   if(userdata.IsUserAnon())
   {
      this.lvars.name = "guy_incognito";
      this.lvars.pword = "random123";
   }
   else
   {
      this.lvars.name = userdata.GetUserName();
      this.lvars.pword = userdata.GetUserPass();
   }
   this.RunQuery(callback,_loc2_);
};
NinjaOnlineClient.prototype.QueryPersBestGoals = function(epNum, ed0, ed1, ed2, ed3, ed4, ld0, ld1, ld2, ld3, ld4, callback)
{
   var _loc2_ = "get_lowest_hs_check_demo.php";
   this.InitQuery(callback);
   this.lvars.episode_number = epNum;
   this.lvars.epdem0 = ed0;
   this.lvars.epdem1 = ed1;
   this.lvars.epdem2 = ed2;
   this.lvars.epdem3 = ed3;
   this.lvars.epdem4 = ed4;
   this.lvars.levdem0 = ld0;
   this.lvars.levdem1 = ld1;
   this.lvars.levdem2 = ld2;
   this.lvars.levdem3 = ld3;
   this.lvars.levdem4 = ld4;
   this.RunQuery(callback,_loc2_);
};
NinjaOnlineClient.prototype.AddNewUser = function(n, p, e, callback)
{
   var _loc2_ = "add_user.php";
   this.InitQuery(callback);
   this.lvars.name = n;
   this.lvars.pword = p;
   this.lvars.email = e;
   this.RunQuery(callback,_loc2_);
};
NinjaOnlineClient.prototype.TestUserLogin = function(n, p, e, callback)
{
   var _loc2_ = "user_query_md5.php";
   this.InitQuery(callback);
   this.lvars.name = n;
   this.lvars.pword = p;
   this.lvars.email = e;
   this.RunQuery(callback,_loc2_);
};
