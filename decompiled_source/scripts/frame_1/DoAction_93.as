function PackOctalString(str)
{
   var _loc10_ = str.length;
   if(_loc10_ % 2 == 1)
   {
      str += "3";
   }
   var _loc9_ = "";
   _loc10_ = str.length;
   var _loc2_ = 0;
   var _loc3_;
   var _loc4_;
   var _loc7_;
   var _loc6_;
   var _loc1_;
   var _loc5_;
   while(_loc2_ < _loc10_)
   {
      _loc3_ = str.charAt(_loc2_);
      _loc4_ = str.charAt(_loc2_ + 1);
      _loc7_ = parseInt(_loc3_,8);
      _loc6_ = parseInt(_loc4_,8);
      _loc1_ = 0;
      _loc1_ += _loc7_ << 3;
      _loc1_ += _loc6_;
      _loc1_ += 34;
      if(91 < _loc1_)
      {
         _loc1_ += 1;
      }
      _loc5_ = String.fromCharCode(_loc1_);
      _loc9_ += _loc5_;
      _loc2_ += 2;
   }
   return _loc9_;
}
function UnpackOctalString(str)
{
   var _loc3_ = "";
   var _loc12_ = str.length;
   var _loc2_ = 0;
   var _loc1_;
   var _loc9_;
   var _loc7_;
   var _loc10_;
   var _loc11_;
   var _loc8_;
   var _loc6_;
   var _loc4_;
   var _loc5_;
   while(_loc2_ < _loc12_)
   {
      _loc1_ = str.charCodeAt(_loc2_);
      if(91 < _loc1_)
      {
         _loc1_ -= 1;
      }
      _loc1_ -= 34;
      _loc9_ = 56;
      _loc7_ = 7;
      _loc10_ = (_loc1_ & _loc9_) >> 3;
      _loc11_ = _loc1_ & _loc7_;
      _loc8_ = new Number(_loc10_);
      _loc6_ = new Number(_loc11_);
      _loc4_ = _loc8_.toString(8);
      _loc5_ = _loc6_.toString(8);
      _loc3_ += _loc4_;
      _loc3_ += _loc5_;
      _loc2_ = _loc2_ + 1;
   }
   if(_loc3_.charAt(_loc3_.length - 1) == "3")
   {
      _loc3_ = _loc3_.substr(0,_loc3_.length - 1);
   }
   return _loc3_;
}
