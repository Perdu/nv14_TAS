PINPUT_L = 0;
PINPUT_R = 1;
PINPUT_J = 2;
PINPUT_JTRIG = 3;
BITSHIFT_L = 0;
BITSHIFT_R = 1;
BITSHIFT_J = 2;
BITSHIFT_JTRIG = 3;
BITMASK_L = 1 << BITSHIFT_L;
BITMASK_R = 1 << BITSHIFT_R;
BITMASK_J = 1 << BITSHIFT_J;
BITMASK_JTRIG = 1 << BITSHIFT_JTRIG;
NinjaGame.prototype.GetInputState_Normal = function(inList)
{
   inList[PINPUT_L] = Key.isDown(this.KEYDEF_L);
   inList[PINPUT_R] = Key.isDown(this.KEYDEF_R);
   var _loc3_ = inList[PINPUT_J];
   if(debug)
   {
      trace("PINPUT_JTRIG");
   }
   inList[PINPUT_J] = Key.isDown(this.KEYDEF_J);
   inList[PINPUT_JTRIG] = inList[PINPUT_J] && !_loc3_;
   if(debug)
   {
      inList[PINPUT_JTRIG] = inList[PINPUT_J];
   }
   if(this.RECORDING_DEMO)
   {
      this.RecordFrame(inList);
   }
};
NinjaGame.prototype.GetDemoTickCount = function()
{
   return this.demoTickCount;
};
