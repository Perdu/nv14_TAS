NinjaUserData.prototype.GetMaxVal = function(curval, oldval)
{
   if(oldval != null)
   {
      if(curval < oldval)
      {
         return oldval;
      }
   }
   return curval;
};
NinjaUserData.prototype.IsOldMaxVal = function(curval, oldval)
{
   if(oldval != null)
   {
      if(curval < oldval)
      {
         return true;
      }
   }
   return false;
};
NinjaUserData.prototype.ImportUserData = function()
{
   this.ImportAndMerge("n_v13_userdata");
   this.ImportAndMerge("n_v13b_userdata");
   this.ImportAndMerge("n_v13d_userdataTESTA");
   this.ImportAndMerge("n_v14_userdata");
   this.SetNumBeaten(this.GetNumUnlockedColors());
   this.Save();
};
NinjaUserData.prototype.ImportAndMerge = function(soname)
{
   var _loc3_ = SharedObject.getLocal(soname,"/");
   var _loc10_ = 0;
   var _loc8_;
   var _loc7_;
   var _loc6_;
   while(_loc10_ < 9)
   {
      _loc8_ = "mission" + _loc10_ + "ep";
      _loc7_ = this.shared.data[_loc8_];
      _loc6_ = _loc3_.data[_loc8_];
      this.shared.data[_loc8_] = this.GetMaxVal(_loc7_,_loc6_);
      _loc10_ = _loc10_ + 1;
   }
   _loc10_ = 0;
   while(_loc10_ < 9)
   {
      _loc8_ = "mission" + _loc10_ + "lev";
      _loc7_ = this.shared.data[_loc8_];
      _loc6_ = _loc3_.data[_loc8_];
      this.shared.data[_loc8_] = this.GetMaxVal(_loc7_,_loc6_);
      _loc10_ = _loc10_ + 1;
   }
   _loc10_ = 0;
   while(_loc10_ < 9)
   {
      _loc8_ = "mission" + _loc10_ + "epB";
      _loc7_ = this.shared.data[_loc8_];
      _loc6_ = _loc3_.data[_loc8_];
      this.shared.data[_loc8_] = this.GetMaxVal(_loc7_,_loc6_);
      _loc10_ = _loc10_ + 1;
   }
   _loc10_ = 0;
   while(_loc10_ < 9)
   {
      _loc8_ = "mission" + _loc10_ + "levB";
      _loc7_ = this.shared.data[_loc8_];
      _loc6_ = _loc3_.data[_loc8_];
      this.shared.data[_loc8_] = this.GetMaxVal(_loc7_,_loc6_);
      _loc10_ = _loc10_ + 1;
   }
   _loc7_ = this.shared.data.killList["zap drone"];
   _loc6_ = _loc3_.data.killList["zap drone"];
   this.shared.data.killList["zap drone"] = this.GetMaxVal(_loc7_,_loc6_);
   _loc7_ = this.shared.data.killList["laser drone"];
   _loc6_ = _loc3_.data.killList["laser drone"];
   this.shared.data.killList["laser drone"] = this.GetMaxVal(_loc7_,_loc6_);
   _loc7_ = this.shared.data.killList["chaingun drone"];
   _loc6_ = _loc3_.data.killList["chaingun drone"];
   this.shared.data.killList["chaingun drone"] = this.GetMaxVal(_loc7_,_loc6_);
   _loc7_ = this.shared.data.killList.thwump;
   _loc6_ = _loc3_.data.killList.thwump;
   this.shared.data.killList.thwump = this.GetMaxVal(_loc7_,_loc6_);
   _loc7_ = this.shared.data.killList["homing rocket"];
   _loc6_ = _loc3_.data.killList["homing rocket"];
   this.shared.data.killList["homing rocket"] = this.GetMaxVal(_loc7_,_loc6_);
   _loc7_ = this.shared.data.killList["floor guard"];
   _loc6_ = _loc3_.data.killList["floor guard"];
   this.shared.data.killList["floor guard"] = this.GetMaxVal(_loc7_,_loc6_);
   _loc7_ = this.shared.data.killList["gauss turret"];
   _loc6_ = _loc3_.data.killList["gauss turret"];
   this.shared.data.killList["gauss turret"] = this.GetMaxVal(_loc7_,_loc6_);
   _loc7_ = this.shared.data.killList.mine;
   _loc6_ = _loc3_.data.killList.mine;
   this.shared.data.killList.mine = this.GetMaxVal(_loc7_,_loc6_);
   _loc7_ = this.shared.data.killList.player;
   _loc6_ = _loc3_.data.killList.player;
   this.shared.data.killList.player = this.GetMaxVal(_loc7_,_loc6_);
   _loc7_ = this.shared.data.secretList[0];
   _loc6_ = _loc3_.data.secretList[0];
   this.shared.data.secretList[0] = this.GetMaxVal(_loc7_,_loc6_);
   _loc10_ = 0;
   var _loc2_;
   while(_loc10_ < 100)
   {
      _loc7_ = this.shared.data.persBest[_loc10_].ep.score;
      _loc6_ = _loc3_.data.persBest[_loc10_].ep.score;
      if(this.IsOldMaxVal(_loc7_,_loc6_))
      {
         this.shared.data.persBest[_loc10_].ep = _loc3_.data.persBest[_loc10_].ep;
      }
      _loc2_ = 0;
      while(_loc2_ < 5)
      {
         _loc7_ = this.shared.data.persBest[_loc10_].lev[_loc2_].score;
         _loc6_ = _loc3_.data.persBest[_loc10_].lev[_loc2_].score;
         if(this.IsOldMaxVal(_loc7_,_loc6_))
         {
            this.shared.data.persBest[_loc10_].lev[_loc2_] = _loc3_.data.persBest[_loc10_].lev[_loc2_];
         }
         _loc2_ = _loc2_ + 1;
      }
      _loc10_ = _loc10_ + 1;
   }
   var _loc5_;
   var _loc9_;
   var _loc4_;
   for(_loc10_ in _loc3_.data.persBestCustom)
   {
      _loc5_ = _loc3_.data.persBestCustom[_loc10_];
      _loc9_ = false;
      if(this.shared.data.persBestCustom[_loc10_] == null)
      {
         _loc9_ = true;
      }
      else if(this.shared.data.persBestCustom[_loc10_].score < _loc5_.score)
      {
         _loc9_ = true;
      }
      if(_loc9_)
      {
         _loc4_ = new Object();
         _loc4_.score = _loc5_.score;
         _loc4_.demo = _loc5_.demo;
         _loc4_.userN = _loc5_.userN;
         _loc4_.userP = _loc5_.userP;
         this.shared.data.persBestCustom[_loc10_] = _loc4_;
      }
   }
   this.shared.data.isImported = true;
   this.Save();
};
