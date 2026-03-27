function EncodeOctalString_RLEo6(str)
{
   var _loc8_ = "";
   var _loc5_ = str.length;
   var _loc3_ = 0;
   var _loc4_;
   var _loc2_;
   var _loc1_;
   var _loc7_;
   while(_loc3_ < _loc5_)
   {
      _loc4_ = str.charAt(_loc3_);
      _loc2_ = 0;
      _loc1_ = _loc3_;
      while(_loc1_ < _loc5_ && _loc2_ < RLEo6_MAX_RUN_LEN)
      {
         if(str.charAt(_loc1_) != _loc4_)
         {
            break;
         }
         _loc2_ = _loc2_ + 1;
         _loc1_ = _loc1_ + 1;
      }
      if(_loc2_ < 5)
      {
         _loc8_ += _loc4_;
      }
      else
      {
         _loc7_ = EncodeCharRun_RLEo6(_loc4_,_loc2_);
         _loc8_ += _loc7_;
         _loc3_ = _loc1_ - 1;
      }
      _loc3_ = _loc3_ + 1;
   }
   return _loc8_;
}
function EncodeCharRun_RLEo6(char, len)
{
   var _loc1_ = "7";
   _loc1_ += char;
   if(len < 5)
   {
      return "";
   }
   len -= 4;
   var _loc8_ = 56;
   var _loc6_ = 7;
   var _loc9_ = (len & _loc8_) >> 3;
   var _loc10_ = len & _loc6_;
   var _loc7_ = new Number(_loc9_);
   var _loc5_ = new Number(_loc10_);
   var _loc3_ = _loc7_.toString(8);
   var _loc4_ = _loc5_.toString(8);
   _loc1_ += _loc3_;
   _loc1_ += _loc4_;
   return _loc1_;
}
function DecodeCharRun_RLEo6(runStr)
{
   var _loc3_ = runStr.charAt(1);
   var _loc5_ = runStr.charAt(2);
   var _loc6_ = runStr.charAt(3);
   var _loc7_ = parseInt(_loc5_,8);
   var _loc8_ = parseInt(_loc6_,8);
   var _loc2_ = 0;
   _loc2_ += _loc7_ << 3;
   _loc2_ += _loc8_;
   _loc2_ += 4;
   var _loc1_ = "";
   while(_loc1_.length < _loc2_)
   {
      _loc1_ += _loc3_;
   }
   return _loc1_;
}
function DecodeOctalString_RLEo6(str)
{
   var _loc5_ = "";
   var _loc7_ = str.length;
   var _loc1_ = 0;
   var _loc2_;
   var _loc3_;
   var _loc4_;
   while(_loc1_ < _loc7_)
   {
      _loc2_ = str.charAt(_loc1_);
      if(_loc2_ == "7")
      {
         _loc3_ = str.substr(_loc1_,4);
         _loc4_ = DecodeCharRun_RLEo6(_loc3_);
         _loc5_ += _loc4_;
         _loc1_ += 3;
      }
      else
      {
         _loc5_ += _loc2_;
      }
      _loc1_ = _loc1_ + 1;
   }
   return _loc5_;
}
RLEo6_MAX_RUN_LEN = 67;
