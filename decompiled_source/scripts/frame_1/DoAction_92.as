function RLEo6c_SetTokenRange(bottom, top)
{
   if(top < bottom)
   {
      return undefined;
   }
   RLEo6c_RUN_CHARSHIFT = bottom;
   RLEo6c_MAX_RUN_LEN = top - bottom;
}
function EncodeOctalString_RLEo6c(str)
{
   var _loc8_ = "";
   var _loc5_ = PackOctalString(str);
   var _loc6_ = _loc5_.length;
   var _loc3_ = 0;
   var _loc4_;
   var _loc2_;
   var _loc1_;
   var _loc7_;
   while(_loc3_ < _loc6_)
   {
      _loc4_ = _loc5_.charAt(_loc3_);
      _loc2_ = 0;
      _loc1_ = _loc3_;
      while(_loc1_ < _loc6_ && _loc2_ < RLEo6c_MAX_RUN_LEN)
      {
         if(_loc5_.charAt(_loc1_) != _loc4_)
         {
            break;
         }
         _loc2_ = _loc2_ + 1;
         _loc1_ = _loc1_ + 1;
      }
      if(_loc2_ < RLEo6c_MIN_RUN_LEN)
      {
         _loc8_ += _loc4_;
      }
      else
      {
         _loc7_ = EncodeCharRun_RLEo6c(_loc4_,_loc2_);
         _loc8_ += _loc7_;
         _loc3_ = _loc1_ - 1;
      }
      _loc3_ = _loc3_ + 1;
   }
   return _loc8_;
}
function EncodeCharRun_RLEo6c(char, len)
{
   var _loc1_ = "";
   len += RLEo6c_RUN_CHARSHIFT;
   var _loc2_ = String.fromCharCode(len);
   _loc1_ += _loc2_;
   _loc1_ += char;
   return _loc1_;
}
function DecodeCharRun_RLEo6c(runStr)
{
   var _loc2_ = runStr.charCodeAt(0);
   _loc2_ -= RLEo6c_RUN_CHARSHIFT;
   var _loc3_ = runStr.charAt(1);
   var _loc1_ = "";
   while(_loc1_.length < _loc2_)
   {
      _loc1_ += _loc3_;
   }
   return _loc1_;
}
function DecodeOctalString_RLEo6c(str)
{
   var _loc7_ = "";
   var _loc8_ = str.length;
   var _loc1_ = 0;
   var _loc4_;
   var _loc3_;
   var _loc6_;
   var _loc5_;
   while(_loc1_ < _loc8_)
   {
      _loc4_ = str.charCodeAt(_loc1_);
      if(RLEo6c_RUN_CHARSHIFT <= _loc4_)
      {
         _loc3_ = str.substr(_loc1_,2);
         _loc6_ = DecodeCharRun_RLEo6c(_loc3_);
         _loc7_ += _loc6_;
         _loc1_ += RLEo6c_MIN_RUN_LEN - 1;
      }
      else
      {
         _loc5_ = str.charAt(_loc1_);
         _loc7_ += _loc5_;
      }
      _loc1_ = _loc1_ + 1;
   }
   var _loc9_ = UnpackOctalString(_loc7_);
   return _loc9_;
}
RLEo6c_RUN_CHARSHIFT = 100;
RLEo6c_MIN_RUN_LEN = 3;
RLEo6c_MAX_RUN_LEN = 50;
