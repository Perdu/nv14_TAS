function NinjaFilesys_Game()
{
   this.outputName = "NLCfromGame";
   this.inputName = "NLCtoGame";
   this.outputLC = new LocalConnection();
   this.outputLC.onStatus = function(stat)
   {
      var _loc1_ = "out:" + stat.level;
      console.AddLine(_loc1_);
   };
   this.inputLC = new LocalConnection();
   this.inputLC.owner = this;
   this.inputLC.ReceiveDebugStr_Game = function(str)
   {
      this.owner.ReceiveDebugStr(str);
   };
   this.inputLC.connect(this.inputName);
}
NinjaFilesys_Game.prototype.ReceiveDebugStr = function(str)
{
   str = " in: " + str;
   console.AddLine(str);
};
NinjaFilesys_Game.prototype.SendDebugStr = function(str)
{
   var _loc2_ = this.outputLC.send(this.outputName,"ReceiveDebugStr",str);
   if(!_loc2_)
   {
      str = "CAN\'T SEND!";
      console.AddLine(str);
   }
};
