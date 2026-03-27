DEMOFRAME_SEPERATION_CHAR = "|";
DEMOTICKS_SEPERATION_CHAR = ":";
BITMASK_FRAME_COMPLEX = BITMASK_L + BITMASK_R + BITMASK_J + BITMASK_JTRIG;
shiftList_Complex = new Array();
shiftList_Complex[0] = 0;
shiftList_Complex[1] = 4;
shiftList_Complex[2] = 8;
shiftList_Complex[3] = 12;
shiftList_Complex[4] = 16;
shiftList_Complex[5] = 20;
shiftList_Complex[6] = 24;
NUM_BITPACKS_COMPLEX = shiftList_Complex.length;
NinjaGame.prototype.StartRecordingDemo_Complex = function()
{
   console.AddLine("-demo recording started..");
   this.GetInputState = this.GetInputState_Normal;
   this.RECORDING_DEMO = true;
   this.demoTickCount = 0;
   this.demoList = new Array();
   this.demoList.push(0);
   this.demoCurShift = 0;
};
NinjaGame.prototype.StopRecordingDemo_Complex = function()
{
   this.RECORDING_DEMO = false;
   this.demoTickCount -= 1;
   if(this.demoTickCount < 0)
   {
      this.demoTickCount = 0;
   }
   console.AddLine("-demo recording stopped.");
};
NinjaGame.prototype.LoadDemo_Complex = function(demoStr)
{
   var _loc4_ = demoStr.split(DEMOTICKS_SEPERATION_CHAR);
   this.demoTickCount = Number(_loc4_[0]);
   var _loc3_ = _loc4_[1].split(DEMOFRAME_SEPERATION_CHAR);
   this.demoList = new Array();
   var _loc2_ = 0;
   while(_loc2_ < _loc3_.length)
   {
      this.demoList[_loc2_] = Number(_loc3_[_loc2_]);
      _loc2_ = _loc2_ + 1;
   }
   console.AddLine("-demo loaded.");
};
NinjaGame.prototype.StartDemoPlayback_Complex = function()
{
   console.AddLine("-demo playback started..");
   this.GetInputState = this.GetInputState_DemoPlayback;
   this.demoCurPlayEntry = 0;
   this.demoCurShift = 0;
};
NinjaGame.prototype.StopDemoPlayback_Complex = function()
{
   console.AddLine("-demo playback stopped.");
   this.GetInputState = this.GetInputState_Normal;
};
NinjaGame.prototype.DumpDemoData_Complex = function()
{
   var _loc3_ = "";
   _loc3_ += this.demoTickCount + DEMOTICKS_SEPERATION_CHAR;
   var _loc2_ = 0;
   while(_loc2_ < this.demoList.length)
   {
      _loc3_ += this.demoList[_loc2_];
      _loc3_ += DEMOFRAME_SEPERATION_CHAR;
      _loc2_ = _loc2_ + 1;
   }
   var _loc4_;
   if(0 < _loc3_.length)
   {
      _loc4_ = _loc3_.lastIndexOf(DEMOFRAME_SEPERATION_CHAR);
      _loc3_ = _loc3_.substring(0,_loc4_);
   }
   return _loc3_;
};
NinjaGame.prototype.RecordFrame_Complex = function(inList)
{
   if(3600 <= this.demoList.length)
   {
      this.StopRecordingDemo();
      return undefined;
   }
   var _loc4_ = Number(inList[PINPUT_L]);
   var _loc3_ = Number(inList[PINPUT_R]);
   var _loc5_ = Number(inList[PINPUT_J]);
   var _loc6_ = Number(inList[PINPUT_JTRIG]);
   var _loc7_ = 0 + (_loc4_ << BITSHIFT_L) + (_loc3_ << BITSHIFT_R) + (_loc5_ << BITSHIFT_J) + (_loc6_ << BITSHIFT_JTRIG);
   var _loc8_ = shiftList_Complex[this.demoCurShift];
   this.demoList[this.demoList.length - 1] += _loc7_ << _loc8_;
   this.demoCurShift = this.demoCurShift + 1;
   if(NUM_BITPACKS_COMPLEX <= this.demoCurShift)
   {
      this.demoList.push(0);
      this.demoCurShift = 0;
   }
   this.demoTickCount = this.demoTickCount + 1;
};
NinjaGame.prototype.GetInputState_DemoPlayback_Complex = function(inList)
{
   if(this.demoTickCount <= game.GetTime())
   {
      this.StopDemoPlayback();
      return undefined;
   }
   var _loc2_ = this.demoList[this.demoCurPlayEntry];
   _loc2_ >>= shiftList_Complex[this.demoCurShift];
   _loc2_ &= BITMASK_FRAME_COMPLEX;
   var _loc5_ = _loc2_ & BITMASK_L;
   var _loc4_ = _loc2_ & BITMASK_R;
   var _loc6_ = _loc2_ & BITMASK_J;
   var _loc7_ = _loc2_ & BITMASK_JTRIG;
   inList[PINPUT_L] = Boolean(_loc5_);
   inList[PINPUT_R] = Boolean(_loc4_);
   inList[PINPUT_J] = Boolean(_loc6_);
   inList[PINPUT_JTRIG] = Boolean(_loc7_);
   this.demoCurShift = this.demoCurShift + 1;
   if(NUM_BITPACKS_COMPLEX <= this.demoCurShift)
   {
      this.demoCurPlayEntry = this.demoCurPlayEntry + 1;
      this.demoCurShift = 0;
   }
};
