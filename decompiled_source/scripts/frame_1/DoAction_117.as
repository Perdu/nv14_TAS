function NinjaUserData()
{
   this.shared = SharedObject.getLocal("n_v14b_userdata","/");
   this.shared.onStatus = function(infoObject)
   {
      var _loc1_ = infoObject.code;
      if(_loc1_ != "SharedObject.Flush.Failed")
      {
         if(_loc1_ == "SharedObject.Flush.Success")
         {
         }
      }
   };
   var _loc4_ = _root._url;
   if(_loc4_.substr(0,4) != "file")
   {
      getURL("http://www.harveycartel.org/metanet/",_top);
   }
   this.BuildUserData();
   if(!this.shared.data.isImported)
   {
      this.ImportUserData();
   }
}
NinjaUserData.prototype.Save = function()
{
   var _loc2_ = this.shared.flush(20000000);
};
NinjaUserData.prototype.SetHighQuality = function(qual)
{
   this.shared.data.highQuality = qual;
   this.Save();
};
NinjaUserData.prototype.IncrementKillCount = function(objname)
{
   this.shared.data.killList[objname] += 1;
};
NinjaUserData.prototype.NotifyEpisodeReached = function(num)
{
   if(num < 10)
   {
      if(this.shared.data.mission0ep < num)
      {
         this.shared.data.mission0ep = num;
         this.shared.data.mission0lev = 0;
         this.Save();
      }
   }
   else if(num < 20)
   {
      if(this.shared.data.mission1ep < num)
      {
         this.shared.data.mission1ep = num;
         this.shared.data.mission1lev = 0;
         this.Save();
      }
   }
   else if(num < 30)
   {
      if(this.shared.data.mission2ep < num)
      {
         this.shared.data.mission2ep = num;
         this.shared.data.mission2lev = 0;
         this.Save();
      }
   }
   else if(num < 40)
   {
      if(this.shared.data.mission3ep < num)
      {
         this.shared.data.mission3ep = num;
         this.shared.data.mission3lev = 0;
         this.Save();
      }
   }
   else if(num < 50)
   {
      if(this.shared.data.mission4ep < num)
      {
         this.shared.data.mission4ep = num;
         this.shared.data.mission4lev = 0;
         this.Save();
      }
   }
   else if(num < 60)
   {
      if(this.shared.data.mission5ep < num)
      {
         this.shared.data.mission5ep = num;
         this.shared.data.mission5lev = 0;
         this.Save();
      }
   }
   else if(num < 70)
   {
      if(this.shared.data.mission6ep < num)
      {
         this.shared.data.mission6ep = num;
         this.shared.data.mission6lev = 0;
         this.Save();
      }
   }
   else if(num < 80)
   {
      if(this.shared.data.mission7ep < num)
      {
         this.shared.data.mission7ep = num;
         this.shared.data.mission7lev = 0;
         this.Save();
      }
   }
   else if(num < 90)
   {
      if(this.shared.data.mission8ep < num)
      {
         this.shared.data.mission8ep = num;
         this.shared.data.mission8lev = 0;
         this.Save();
      }
   }
   else if(num < 100)
   {
      if(this.shared.data.mission9ep < num)
      {
         this.shared.data.mission9ep = num;
         this.shared.data.mission9lev = 0;
         this.Save();
      }
   }
};
NinjaUserData.prototype.NotifyEpisodeBeaten = function(num)
{
   if(num < 10)
   {
      if(this.shared.data.mission0epB < num)
      {
         this.shared.data.mission0epB = num;
         this.shared.data.mission0levB = 0;
         this.Save();
      }
   }
   else if(num < 20)
   {
      if(this.shared.data.mission1epB < num)
      {
         this.shared.data.mission1epB = num;
         this.shared.data.mission1levB = 0;
         this.Save();
      }
   }
   else if(num < 30)
   {
      if(this.shared.data.mission2epB < num)
      {
         this.shared.data.mission2epB = num;
         this.shared.data.mission2levB = 0;
         this.Save();
      }
   }
   else if(num < 40)
   {
      if(this.shared.data.mission3epB < num)
      {
         this.shared.data.mission3epB = num;
         this.shared.data.mission3levB = 0;
         this.Save();
      }
   }
   else if(num < 50)
   {
      if(this.shared.data.mission4epB < num)
      {
         this.shared.data.mission4epB = num;
         this.shared.data.mission4levB = 0;
         this.Save();
      }
   }
   else if(num < 60)
   {
      if(this.shared.data.mission5epB < num)
      {
         this.shared.data.mission5epB = num;
         this.shared.data.mission5levB = 0;
         this.Save();
      }
   }
   else if(num < 70)
   {
      if(this.shared.data.mission6epB < num)
      {
         this.shared.data.mission6epB = num;
         this.shared.data.mission6levB = 0;
         this.Save();
      }
   }
   else if(num < 80)
   {
      if(this.shared.data.mission7epB < num)
      {
         this.shared.data.mission7epB = num;
         this.shared.data.mission7levB = 0;
         this.Save();
      }
   }
   else if(num < 90)
   {
      if(this.shared.data.mission8epB < num)
      {
         this.shared.data.mission8epB = num;
         this.shared.data.mission8levB = 0;
         this.Save();
      }
   }
   else if(num < 100)
   {
      if(this.shared.data.mission9epB < num)
      {
         this.shared.data.mission9epB = num;
         this.shared.data.mission9levB = 0;
         this.Save();
      }
   }
};
NinjaUserData.prototype.NotifyLevelReached = function(epNum, levNum)
{
   if(epNum < 10)
   {
      if(this.shared.data.mission0ep == epNum)
      {
         if(this.shared.data.mission0lev < levNum)
         {
            this.shared.data.mission0lev = levNum;
            this.Save();
         }
      }
   }
   else if(epNum < 20)
   {
      if(this.shared.data.mission1ep == epNum)
      {
         if(this.shared.data.mission1lev < levNum)
         {
            this.shared.data.mission1lev = levNum;
            this.Save();
         }
      }
   }
   else if(epNum < 30)
   {
      if(this.shared.data.mission2ep == epNum)
      {
         if(this.shared.data.mission2lev < levNum)
         {
            this.shared.data.mission2lev = levNum;
            this.Save();
         }
      }
   }
   else if(epNum < 40)
   {
      if(this.shared.data.mission3ep == epNum)
      {
         if(this.shared.data.mission3lev < levNum)
         {
            this.shared.data.mission3lev = levNum;
            this.Save();
         }
      }
   }
   else if(epNum < 50)
   {
      if(this.shared.data.mission4ep == epNum)
      {
         if(this.shared.data.mission4lev < levNum)
         {
            this.shared.data.mission4lev = levNum;
            this.Save();
         }
      }
   }
   else if(epNum < 60)
   {
      if(this.shared.data.mission5ep == epNum)
      {
         if(this.shared.data.mission5lev < levNum)
         {
            this.shared.data.mission5lev = levNum;
            this.Save();
         }
      }
   }
   else if(epNum < 70)
   {
      if(this.shared.data.mission6ep == epNum)
      {
         if(this.shared.data.mission6lev < levNum)
         {
            this.shared.data.mission6lev = levNum;
            this.Save();
         }
      }
   }
   else if(epNum < 80)
   {
      if(this.shared.data.mission7ep == epNum)
      {
         if(this.shared.data.mission7lev < levNum)
         {
            this.shared.data.mission7lev = levNum;
            this.Save();
         }
      }
   }
   else if(epNum < 90)
   {
      if(this.shared.data.mission8ep == epNum)
      {
         if(this.shared.data.mission8lev < levNum)
         {
            this.shared.data.mission8lev = levNum;
            this.Save();
         }
      }
   }
   else if(epNum < 100)
   {
      if(this.shared.data.mission9ep == epNum)
      {
         if(this.shared.data.mission9lev < levNum)
         {
            this.shared.data.mission9lev = levNum;
            this.Save();
         }
      }
   }
};
NinjaUserData.prototype.NotifyLevelBeaten = function(epNum, levNum)
{
   if(epNum < 10)
   {
      if(this.shared.data.mission0epB == epNum)
      {
         if(this.shared.data.mission0levB < levNum)
         {
            this.shared.data.mission0levB = levNum;
            this.Save();
         }
      }
   }
   else if(epNum < 20)
   {
      if(this.shared.data.mission1epB == epNum)
      {
         if(this.shared.data.mission1levB < levNum)
         {
            this.shared.data.mission1levB = levNum;
            this.Save();
         }
      }
   }
   else if(epNum < 30)
   {
      if(this.shared.data.mission2epB == epNum)
      {
         if(this.shared.data.mission2levB < levNum)
         {
            this.shared.data.mission2levB = levNum;
            this.Save();
         }
      }
   }
   else if(epNum < 40)
   {
      if(this.shared.data.mission3epB == epNum)
      {
         if(this.shared.data.mission3levB < levNum)
         {
            this.shared.data.mission3levB = levNum;
            this.Save();
         }
      }
   }
   else if(epNum < 50)
   {
      if(this.shared.data.mission4epB == epNum)
      {
         if(this.shared.data.mission4levB < levNum)
         {
            this.shared.data.mission4levB = levNum;
            this.Save();
         }
      }
   }
   else if(epNum < 60)
   {
      if(this.shared.data.mission5epB == epNum)
      {
         if(this.shared.data.mission5levB < levNum)
         {
            this.shared.data.mission5levB = levNum;
            this.Save();
         }
      }
   }
   else if(epNum < 70)
   {
      if(this.shared.data.mission6epB == epNum)
      {
         if(this.shared.data.mission6levB < levNum)
         {
            this.shared.data.mission6levB = levNum;
            this.Save();
         }
      }
   }
   else if(epNum < 80)
   {
      if(this.shared.data.mission7epB == epNum)
      {
         if(this.shared.data.mission7levB < levNum)
         {
            this.shared.data.mission7levB = levNum;
            this.Save();
         }
      }
   }
   else if(epNum < 90)
   {
      if(this.shared.data.mission8epB == epNum)
      {
         if(this.shared.data.mission8levB < levNum)
         {
            this.shared.data.mission8levB = levNum;
            this.Save();
         }
      }
   }
   else if(epNum < 100)
   {
      if(this.shared.data.mission9epB == epNum)
      {
         if(this.shared.data.mission9levB < levNum)
         {
            this.shared.data.mission9levB = levNum;
            this.Save();
         }
      }
   }
};
NinjaUserData.prototype.SetLeftKey = function(k)
{
   this.shared.data.keyL = k;
   this.Save();
   game.SetKeyDefs(this.shared.data.keyJ,this.shared.data.keyL,this.shared.data.keyR);
};
NinjaUserData.prototype.SetRightKey = function(k)
{
   this.shared.data.keyR = k;
   this.Save();
   game.SetKeyDefs(this.shared.data.keyJ,this.shared.data.keyL,this.shared.data.keyR);
};
NinjaUserData.prototype.SetJumpKey = function(k)
{
   this.shared.data.keyJ = k;
   this.Save();
   game.SetKeyDefs(this.shared.data.keyJ,this.shared.data.keyL,this.shared.data.keyR);
};
NinjaUserData.prototype.SetKillKey = function(k)
{
   this.shared.data.keyK = k;
   this.Save();
};
NinjaUserData.prototype.SetPauseKey = function(k)
{
   this.shared.data.keyP = k;
   this.Save();
};
NinjaUserData.prototype.SetBossKey = function(k)
{
   APP_BOSS_KEY = k;
   this.shared.data.keyB = k;
   this.Save();
};
NinjaUserData.prototype.SetVol = function(v)
{
   this.shared.data.vol = v;
   this.Save();
};
NinjaUserData.prototype.SetPersBestActive = function(act)
{
   this.shared.data.persbestActive = act;
   this.Save();
};
NinjaUserData.prototype.SetOnlinePath = function(path)
{
   this.shared.data.onlinePath = path;
   this.Save();
};
NinjaUserData.prototype.SetOnlineActive = function(act)
{
   this.shared.data.onlineActive = act;
   this.Save();
};
NinjaUserData.prototype.SetUserAnon = function(isAnon)
{
   this.shared.data.userAnon = isAnon;
   this.Save();
};
NinjaUserData.prototype.SetUserName = function(n)
{
   this.shared.data.username = n;
   this.Save();
};
NinjaUserData.prototype.SetUserPass = function(p)
{
   this.shared.data.userpass = p;
   this.Save();
};
NinjaUserData.prototype.SetUserEmail = function(p)
{
   this.shared.data.useremail = p;
   this.Save();
};
NinjaUserData.prototype.SetSecret = function(secnum, secval)
{
   this.shared.data.secretList[secnum] = secval;
   this.Save();
};
NinjaUserData.prototype.SetPractiseMode = function(isActive)
{
   this.shared.data.practiseMode = isActive;
   this.Save();
};
NinjaUserData.prototype.GetNinjaColor = function()
{
   if(this.IsNinjaColorCustom())
   {
      return this.shared.data.ninjaColorCustom;
   }
   return this.shared.data.ninjaColor;
};
NinjaUserData.prototype.GetNinjaColor_Custom = function()
{
   return this.shared.data.ninjaColorCustom;
};
NinjaUserData.prototype.IsNinjaColorCustom = function()
{
   return this.shared.data.ninjaColorIsCustom;
};
NinjaUserData.prototype.SetNinjaColor = function(col, isCustom)
{
   if(isCustom)
   {
      this.shared.data.ninjaColorCustom = col;
   }
   else
   {
      this.shared.data.ninjaColor = col;
   }
   this.shared.data.ninjaColorIsCustom = isCustom;
   this.Save();
};
NinjaUserData.prototype.GetNumUnlockedColors = function()
{
   var _loc5_ = 0;
   var _loc2_ = 0;
   var _loc3_;
   var _loc4_;
   while(_loc2_ < 10)
   {
      _loc3_ = this.GetEpisodeBeaten(_loc2_);
      if(9 + _loc2_ * 10 <= _loc3_)
      {
         _loc4_ = this.GetLevelBeaten(_loc3_);
         if(_loc4_ == 4)
         {
            _loc5_ = _loc5_ + 1;
         }
      }
      _loc2_ = _loc2_ + 1;
   }
   return _loc5_;
};
NinjaUserData.prototype.SetCustomFlavourUnlocked = function(bool)
{
   this.shared.data.customflavunlocked = bool;
   this.Save();
};
NinjaUserData.prototype.GetCustomFlavourUnlocked = function(bool)
{
   return this.shared.data.customflavunlocked;
};
NinjaUserData.prototype.GetNumBeaten = function()
{
   return this.shared.data.hackynumbeaten;
};
NinjaUserData.prototype.SetNumBeaten = function(n)
{
   this.shared.data.hackynumbeaten = n;
   this.Save();
};
NinjaUserData.prototype.GetPractiseMode = function(isActive)
{
   return this.shared.data.practiseMode;
};
NinjaUserData.prototype.GetHighQuality = function()
{
   return this.shared.data.highQuality;
};
NinjaUserData.prototype.GetSecret = function(secnum)
{
   return this.shared.data.secretList[secnum];
};
NinjaUserData.prototype.GetKillList = function()
{
   return this.shared.data.killList;
};
NinjaUserData.prototype.GetLeftKey = function()
{
   return this.shared.data.keyL;
};
NinjaUserData.prototype.GetRightKey = function()
{
   return this.shared.data.keyR;
};
NinjaUserData.prototype.GetJumpKey = function()
{
   return this.shared.data.keyJ;
};
NinjaUserData.prototype.GetKillKey = function()
{
   return this.shared.data.keyK;
};
NinjaUserData.prototype.GetPauseKey = function()
{
   return this.shared.data.keyP;
};
NinjaUserData.prototype.GetBossKey = function()
{
   return this.shared.data.keyB;
};
NinjaUserData.prototype.GetVol = function()
{
   return this.shared.data.vol;
};
NinjaUserData.prototype.GetOnlineActive = function()
{
   return this.shared.data.onlineActive;
};
NinjaUserData.prototype.GetPersBestActive = function()
{
   return this.shared.data.persbestActive;
};
NinjaUserData.prototype.GetOnlinePath = function()
{
   return this.shared.data.onlinePath;
};
NinjaUserData.prototype.GetUserName = function()
{
   return this.shared.data.username;
};
NinjaUserData.prototype.GetUserPass = function()
{
   return this.shared.data.userpass;
};
NinjaUserData.prototype.GetUserEmail = function()
{
   return this.shared.data.useremail;
};
NinjaUserData.prototype.IsUserAnon = function()
{
   return this.shared.data.userAnon;
};
NinjaUserData.prototype.GetEpisodeReached = function(setNum)
{
   if(setNum == 0)
   {
      return this.shared.data.mission0ep;
   }
   if(setNum == 1)
   {
      return this.shared.data.mission1ep;
   }
   if(setNum == 2)
   {
      return this.shared.data.mission2ep;
   }
   if(setNum == 3)
   {
      return this.shared.data.mission3ep;
   }
   if(setNum == 4)
   {
      return this.shared.data.mission4ep;
   }
   if(setNum == 5)
   {
      return this.shared.data.mission5ep;
   }
   if(setNum == 6)
   {
      return this.shared.data.mission6ep;
   }
   if(setNum == 7)
   {
      return this.shared.data.mission7ep;
   }
   if(setNum == 8)
   {
      return this.shared.data.mission8ep;
   }
   if(setNum == 9)
   {
      return this.shared.data.mission9ep;
   }
   return 0;
};
NinjaUserData.prototype.GetLevelReached = function(epNum)
{
   if(epNum < 10)
   {
      if(epNum == this.shared.data.mission0ep)
      {
         return this.shared.data.mission0lev;
      }
      return 4;
   }
   if(epNum < 20)
   {
      if(epNum == this.shared.data.mission1ep)
      {
         return this.shared.data.mission1lev;
      }
      return 4;
   }
   if(epNum < 30)
   {
      if(epNum == this.shared.data.mission2ep)
      {
         return this.shared.data.mission2lev;
      }
      return 4;
   }
   if(epNum < 40)
   {
      if(epNum == this.shared.data.mission3ep)
      {
         return this.shared.data.mission3lev;
      }
      return 4;
   }
   if(epNum < 50)
   {
      if(epNum == this.shared.data.mission4ep)
      {
         return this.shared.data.mission4lev;
      }
      return 4;
   }
   if(epNum < 60)
   {
      if(epNum == this.shared.data.mission5ep)
      {
         return this.shared.data.mission5lev;
      }
      return 4;
   }
   if(epNum < 70)
   {
      if(epNum == this.shared.data.mission6ep)
      {
         return this.shared.data.mission6lev;
      }
      return 4;
   }
   if(epNum < 80)
   {
      if(epNum == this.shared.data.mission7ep)
      {
         return this.shared.data.mission7lev;
      }
      return 4;
   }
   if(epNum < 90)
   {
      if(epNum == this.shared.data.mission8ep)
      {
         return this.shared.data.mission8lev;
      }
      return 4;
   }
   if(epNum < 100)
   {
      if(epNum == this.shared.data.mission9ep)
      {
         return this.shared.data.mission9lev;
      }
      return 4;
   }
   return 0;
};
NinjaUserData.prototype.ValidateEpisodeReached = function(num)
{
   if(num < 10)
   {
      if(num <= this.shared.data.mission0ep)
      {
         return true;
      }
   }
   else if(num < 20)
   {
      if(num <= this.shared.data.mission1ep)
      {
         return true;
      }
   }
   else if(num < 30)
   {
      if(num <= this.shared.data.mission2ep)
      {
         return true;
      }
   }
   else if(num < 40)
   {
      if(num <= this.shared.data.mission3ep)
      {
         return true;
      }
   }
   else if(num < 50)
   {
      if(num <= this.shared.data.mission4ep)
      {
         return true;
      }
   }
   else if(num < 60)
   {
      if(num <= this.shared.data.mission5ep)
      {
         return true;
      }
   }
   else if(num < 70)
   {
      if(num <= this.shared.data.mission6ep)
      {
         return true;
      }
   }
   else if(num < 80)
   {
      if(num <= this.shared.data.mission7ep)
      {
         return true;
      }
   }
   else if(num < 90)
   {
      if(num <= this.shared.data.mission8ep)
      {
         return true;
      }
   }
   else
   {
      if(num >= 100)
      {
         return false;
      }
      if(num <= this.shared.data.mission9ep)
      {
         return true;
      }
   }
};
NinjaUserData.prototype.GetEpisodeBeaten = function(setNum)
{
   if(setNum == 0)
   {
      return this.shared.data.mission0epB;
   }
   if(setNum == 1)
   {
      return this.shared.data.mission1epB;
   }
   if(setNum == 2)
   {
      return this.shared.data.mission2epB;
   }
   if(setNum == 3)
   {
      return this.shared.data.mission3epB;
   }
   if(setNum == 4)
   {
      return this.shared.data.mission4epB;
   }
   if(setNum == 5)
   {
      return this.shared.data.mission5epB;
   }
   if(setNum == 6)
   {
      return this.shared.data.mission6epB;
   }
   if(setNum == 7)
   {
      return this.shared.data.mission7epB;
   }
   if(setNum == 8)
   {
      return this.shared.data.mission8epB;
   }
   if(setNum == 9)
   {
      return this.shared.data.mission9epB;
   }
   return 0;
};
NinjaUserData.prototype.GetLevelBeaten = function(epNum)
{
   if(epNum < 10)
   {
      if(epNum == this.shared.data.mission0epB)
      {
         return this.shared.data.mission0levB;
      }
      if(epNum < this.shared.data.mission0epB)
      {
         return 4;
      }
      if(this.shared.data.mission0epB < epNum)
      {
         return -1;
      }
   }
   else if(epNum < 20)
   {
      if(epNum == this.shared.data.mission1epB)
      {
         return this.shared.data.mission1levB;
      }
      if(epNum < this.shared.data.mission1epB)
      {
         return 4;
      }
      if(this.shared.data.mission1epB < epNum)
      {
         return -1;
      }
   }
   else if(epNum < 30)
   {
      if(epNum == this.shared.data.mission2epB)
      {
         return this.shared.data.mission2levB;
      }
      if(epNum < this.shared.data.mission2epB)
      {
         return 4;
      }
      if(this.shared.data.mission2epB < epNum)
      {
         return -1;
      }
   }
   else if(epNum < 40)
   {
      if(epNum == this.shared.data.mission3epB)
      {
         return this.shared.data.mission3levB;
      }
      if(epNum < this.shared.data.mission3epB)
      {
         return 4;
      }
      if(this.shared.data.mission3epB < epNum)
      {
         return -1;
      }
   }
   else if(epNum < 50)
   {
      if(epNum == this.shared.data.mission4epB)
      {
         return this.shared.data.mission4levB;
      }
      if(epNum < this.shared.data.mission4epB)
      {
         return 4;
      }
      if(this.shared.data.mission4epB < epNum)
      {
         return -1;
      }
   }
   else if(epNum < 60)
   {
      if(epNum == this.shared.data.mission5epB)
      {
         return this.shared.data.mission5levB;
      }
      if(epNum < this.shared.data.mission5epB)
      {
         return 4;
      }
      if(this.shared.data.mission5epB < epNum)
      {
         return -1;
      }
   }
   else if(epNum < 70)
   {
      if(epNum == this.shared.data.mission6epB)
      {
         return this.shared.data.mission6levB;
      }
      if(epNum < this.shared.data.mission6epB)
      {
         return 4;
      }
      if(this.shared.data.mission6epB < epNum)
      {
         return -1;
      }
   }
   else if(epNum < 80)
   {
      if(epNum == this.shared.data.mission7epB)
      {
         return this.shared.data.mission7levB;
      }
      if(epNum < this.shared.data.mission7epB)
      {
         return 4;
      }
      if(this.shared.data.mission7epB < epNum)
      {
         return -1;
      }
   }
   else if(epNum < 90)
   {
      if(epNum == this.shared.data.mission8epB)
      {
         return this.shared.data.mission8levB;
      }
      if(epNum < this.shared.data.mission8epB)
      {
         return 4;
      }
      if(this.shared.data.mission8epB < epNum)
      {
         return -1;
      }
   }
   else
   {
      if(epNum >= 100)
      {
         return 0;
      }
      if(epNum == this.shared.data.mission9epB)
      {
         return this.shared.data.mission9levB;
      }
      if(epNum < this.shared.data.mission9epB)
      {
         return 4;
      }
      if(this.shared.data.mission9epB < epNum)
      {
         return -1;
      }
   }
};
NinjaUserData.prototype.ValidateEpisodeBeaten = function(num)
{
   if(num < 10)
   {
      if(num <= this.shared.data.mission0epB)
      {
         return true;
      }
   }
   else if(num < 20)
   {
      if(num <= this.shared.data.mission1epB)
      {
         return true;
      }
   }
   else if(num < 30)
   {
      if(num <= this.shared.data.mission2epB)
      {
         return true;
      }
   }
   else if(num < 40)
   {
      if(num <= this.shared.data.mission3epB)
      {
         return true;
      }
   }
   else if(num < 50)
   {
      if(num <= this.shared.data.mission4epB)
      {
         return true;
      }
   }
   else if(num < 60)
   {
      if(num <= this.shared.data.mission5epB)
      {
         return true;
      }
   }
   else if(num < 70)
   {
      if(num <= this.shared.data.mission6epB)
      {
         return true;
      }
   }
   else if(num < 80)
   {
      if(num <= this.shared.data.mission7epB)
      {
         return true;
      }
   }
   else if(num < 90)
   {
      if(num <= this.shared.data.mission8epB)
      {
         return true;
      }
   }
   else
   {
      if(num >= 100)
      {
         return false;
      }
      if(num <= this.shared.data.mission9epB)
      {
         return true;
      }
   }
};
NinjaUserData.prototype.GetPersBest_Custom = function(leveldata)
{
   var _loc2_ = this.shared.data.persBestCustom[leveldata];
   return _loc2_;
};
NinjaUserData.prototype.SetPersBest_Custom = function(leveldata, score, demo)
{
   var _loc2_ = new Object();
   _loc2_.score = score;
   _loc2_.demo = demo;
   _loc2_.userN = this.GetUserName();
   _loc2_.userP = this.GetUserPass();
   this.shared.data.persBestCustom[leveldata] = _loc2_;
   this.Save();
};
NinjaUserData.prototype.GetPersBest_Episode = function(epNum)
{
   return this.shared.data.persBest[epNum];
};
NinjaUserData.prototype.GetPersBest_Level = function(epNum, levNum)
{
   return this.shared.data.persBest[epNum].lev[levNum];
};
NinjaUserData.prototype.SetPersBest_Episode = function(epNum, score, dList)
{
   var _loc2_ = this.shared.data.persBest[epNum].ep;
   _loc2_.fresh = true;
   _loc2_.score = score;
   _loc2_.demo0 = dList[0];
   _loc2_.demo1 = dList[1];
   _loc2_.demo2 = dList[2];
   _loc2_.demo3 = dList[3];
   _loc2_.demo4 = dList[4];
   _loc2_.userN = this.GetUserName();
   _loc2_.userP = this.GetUserPass();
   this.Save();
};
NinjaUserData.prototype.SetPersBest_Level = function(epNum, levNum, score, d)
{
   var _loc2_ = this.shared.data.persBest[epNum].lev[levNum];
   _loc2_.fresh = true;
   _loc2_.score = score;
   _loc2_.demo = d;
   _loc2_.userN = this.GetUserName();
   _loc2_.userP = this.GetUserPass();
   this.Save();
};
NinjaUserData.prototype.Unfresh_Level = function(epNum, levNum)
{
   this.shared.data.persBest[epNum].lev[levNum].fresh = false;
   this.Save();
};
NinjaUserData.prototype.Unfresh_Episode = function(epNum)
{
   this.shared.data.persBest[epNum].ep.fresh = false;
   this.Save();
};
N_USERDATA_PENDING_LEV = new Object();
NinjaUserData.prototype.SubmitPersBest_Level = function(epNum, levNum, score)
{
   _root.N_USERDATA_PENDING_LEV = new Object();
   N_USERDATA_PENDING_LEV.ep = epNum;
   N_USERDATA_PENDING_LEV.lev = levNum;
   N_USERDATA_PENDING_LEV.score = score;
};
NinjaUserData.prototype.SubmitPersBest_Level_Finish = function(str)
{
   this.SetPersBest_Level(N_USERDATA_PENDING_LEV.ep,N_USERDATA_PENDING_LEV.lev,N_USERDATA_PENDING_LEV.score,str);
};
