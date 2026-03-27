BITMASK_BOTTOM30 = 0;
var i = 0;
while(i < 30)
{
   BITMASK_BOTTOM30 += 1 << i;
   i++;
}
BITMASK_FRAME_COMPRESSED = BITMASK_L + BITMASK_R + BITMASK_J;
shiftList_Compressed = new Array();
shiftList_Compressed[0] = 27;
shiftList_Compressed[1] = 24;
shiftList_Compressed[2] = 21;
shiftList_Compressed[3] = 18;
shiftList_Compressed[4] = 15;
shiftList_Compressed[5] = 12;
shiftList_Compressed[6] = 9;
shiftList_Compressed[7] = 6;
shiftList_Compressed[8] = 3;
shiftList_Compressed[9] = 0;
NUM_BITPACKS_COMPRESSED = shiftList_Compressed.length;
NinjaGame.prototype.StartRecordingDemo_Compressed = function()
{
   console.AddLine("-demo recording started..");
   this.GetInputState = this.GetInputState_Normal;
   this.RECORDING_DEMO = true;
   this.demoTickCount = 0;
   this.demoList = new Array();
   this.demoList.push(0);
   this.demoCurShift = 0;
};
NinjaGame.prototype.StopRecordingDemo_Compressed = function()
{
   this.RECORDING_DEMO = false;
   this.demoTickCount -= 1;
   if(this.demoTickCount < 0)
   {
      this.demoTickCount = 0;
   }
   console.AddLine("-demo recording stopped.");
};
NinjaGame.prototype.StartDemoPlayback_Compressed = function()
{
   console.AddLine("-demo playback started..");
   this.GetInputState = this.GetInputState_DemoPlayback;
   this.jtrig_playback_cache = false;
   this.demoCurPlayEntry = 0;
   this.demoCurShift = 0;
};
NinjaGame.prototype.StopDemoPlayback_Compressed = function()
{
   console.AddLine("-demo playback stopped.");
   this.GetInputState = this.GetInputState_Normal;
};
NinjaGame.prototype.RecordFrame_Compressed = function(inList)
{
   if(5000 <= this.demoList.length)
   {
      this.StopRecordingDemo();
      return undefined;
   }
   if(inList[PINPUT_L] && inList[PINPUT_R])
   {
      inList[PINPUT_R] = false;
      inList[PINPUT_L] = false;
   }
   var _loc4_ = Number(inList[PINPUT_L]);
   var _loc3_ = Number(inList[PINPUT_R]);
   var _loc5_ = Number(inList[PINPUT_J]);
   var _loc6_ = 0 + (_loc4_ << BITSHIFT_L) + (_loc3_ << BITSHIFT_R) + (_loc5_ << BITSHIFT_J);
   var _loc7_ = shiftList_Compressed[this.demoCurShift];
   this.demoList[this.demoList.length - 1] += _loc6_ << _loc7_;
   this.demoCurShift = this.demoCurShift + 1;
   if(NUM_BITPACKS_COMPRESSED <= this.demoCurShift)
   {
      this.demoList.push(0);
      this.demoCurShift = 0;
   }
   this.demoTickCount = this.demoTickCount + 1;
};
NinjaGame.prototype.GetInputState_DemoPlayback_Compressed = function(inList)
{
   if(this.demoTickCount <= game.GetTime())
   {
      this.StopDemoPlayback();
      return undefined;
   }
   var _loc2_ = this.demoList[this.demoCurPlayEntry];
   _loc2_ >>= shiftList_Compressed[this.demoCurShift];
   _loc2_ &= BITMASK_FRAME_COMPRESSED;
   var _loc5_ = _loc2_ & BITMASK_L;
   var _loc4_ = _loc2_ & BITMASK_R;
   var _loc6_ = _loc2_ & BITMASK_J;
   inList[PINPUT_L] = Boolean(_loc5_);
   inList[PINPUT_R] = Boolean(_loc4_);
   inList[PINPUT_J] = Boolean(_loc6_);
   inList[PINPUT_JTRIG] = inList[PINPUT_J] && !this.jtrig_playback_cache;
   this.jtrig_playback_cache = inList[PINPUT_J];
   this.demoCurShift = this.demoCurShift + 1;
   if(NUM_BITPACKS_COMPRESSED <= this.demoCurShift)
   {
      this.demoCurPlayEntry = this.demoCurPlayEntry + 1;
      this.demoCurShift = 0;
   }
};
NinjaGame.prototype.LoadDemo_Compressed = function(demoStr)
{
   var _loc5_ = DecompressDemo(demoStr);
   this.demoList = new Array();
   var _loc2_ = 0;
   var _loc4_;
   var _loc3_;
   while(_loc2_ < _loc5_.length)
   {
      _loc4_ = parseInt(_loc5_.substr(_loc2_,10),8);
      _loc3_ = new Number(_loc4_);
      this.demoList.push(_loc3_.valueOf());
      _loc2_ += 10;
   }
   console.AddLine("-demo loaded.");
};
NinjaGame.prototype.DumpDemoData_Compressed = function()
{
   var _loc6_ = "";
   var _loc3_ = 0;
   var _loc5_;
   var _loc4_;
   var _loc2_;
   while(_loc3_ < this.demoList.length)
   {
      _loc5_ = this.demoList[_loc3_] & BITMASK_BOTTOM30;
      _loc4_ = new Number(_loc5_);
      _loc2_ = _loc4_.toString(8);
      while(_loc2_.length < 10)
      {
         _loc2_ = "0" + _loc2_;
      }
      _loc6_ += _loc2_;
      _loc3_ = _loc3_ + 1;
   }
   var _loc7_ = CompressDemo(_loc6_);
   return _loc7_;
};
