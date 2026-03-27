function CompressDemo(str)
{
   var _loc2_ = EncodeOctalString_RLEo6(str);
   var _loc1_ = EncodeOctalString_RLEo6c(_loc2_);
   _loc1_ = "A" + _loc1_;
   return _loc1_;
}
function DecompressDemo(str)
{
   var _loc2_ = DecodeOctalString_RLEo6c(str.substr(1));
   var _loc1_ = DecodeOctalString_RLEo6(_loc2_);
   return _loc1_;
}
NinjaGame.prototype.InstallCompressedCodec = function()
{
   this.StartRecordingDemo = this.StartRecordingDemo_Compressed;
   this.StopRecordingDemo = this.StopRecordingDemo_Compressed;
   this.StartDemoPlayback = this.StartDemoPlayback_Compressed;
   this.StopDemoPlayback = this.StopDemoPlayback_Compressed;
   this.RecordFrame = this.RecordFrame_Compressed;
   this.GetInputState_DemoPlayback = this.GetInputState_DemoPlayback_Compressed;
};
NinjaGame.prototype.InstallComplexCodec = function()
{
   this.StartRecordingDemo = this.StartRecordingDemo_Complex;
   this.StopRecordingDemo = this.StopRecordingDemo_Complex;
   this.StartDemoPlayback = this.StartDemoPlayback_Complex;
   this.StopDemoPlayback = this.StopDemoPlayback_Complex;
   this.RecordFrame = this.RecordFrame_Complex;
   this.GetInputState_DemoPlayback = this.GetInputState_DemoPlayback_Complex;
};
