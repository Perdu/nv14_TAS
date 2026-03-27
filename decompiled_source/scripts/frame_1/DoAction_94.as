function BeginIncrementalCompression(str, callback)
{
   _root.APP_INC_ENCODE_SOURCE = str;
   _root.APP_INC_ENCODE_OUTPUT = "";
   _root.APP_INC_ENCODE_CALLBACK = callback;
   _root.APP_INC_ENCODE_STEP = 0;
   _root.APP_INC_ENCODE_ITERATOR = 0;
   _root.APP_INC_ENCODE_STRLEN = APP_INC_ENCODE_SOURCE.length;
   _root.APP_INC_ENCODE_INTERVAL = setInterval(_root.CompressDemo_Inc,15);
}
function CompressDemo_Inc(str)
{
   var _loc1_;
   if(APP_INC_ENCODE_STEP == 0)
   {
      if(!EncodeOctalString_RLEo6_Inc())
      {
         APP_INC_ENCODE_STEP = 1;
         APP_INC_ENCODE_ITERATOR = 0;
         APP_INC_ENCODE_SOURCE = PackOctalString(APP_INC_ENCODE_OUTPUT);
         APP_INC_ENCODE_OUTPUT = "";
         APP_INC_ENCODE_STRLEN = APP_INC_ENCODE_SOURCE.length;
      }
   }
   else if(APP_INC_ENCODE_STEP == 1)
   {
      if(!EncodeOctalString_RLEo6c_Inc())
      {
         _loc1_ = "A" + APP_INC_ENCODE_OUTPUT;
         APP_INC_ENCODE_CALLBACK(_loc1_);
         clearInterval(APP_INC_ENCODE_INTERVAL);
      }
   }
}
function EncodeOctalString_RLEo6_Inc()
{
   var _loc6_ = 0;
   var _loc7_ = 40;
   var _loc4_ = APP_INC_ENCODE_SOURCE;
   var _loc3_;
   var _loc2_;
   var _loc1_;
   var _loc5_;
   while(_loc6_ < _loc7_)
   {
      _loc3_ = _loc4_.charAt(APP_INC_ENCODE_ITERATOR);
      _loc2_ = 0;
      _loc1_ = APP_INC_ENCODE_ITERATOR;
      while(_loc1_ < APP_INC_ENCODE_STRLEN && _loc2_ < RLEo6_MAX_RUN_LEN)
      {
         if(_loc4_.charAt(_loc1_) != _loc3_)
         {
            break;
         }
         _loc2_ = _loc2_ + 1;
         _loc1_ = _loc1_ + 1;
      }
      if(_loc2_ < 5)
      {
         APP_INC_ENCODE_OUTPUT += _loc3_;
      }
      else
      {
         _loc5_ = EncodeCharRun_RLEo6(_loc3_,_loc2_);
         APP_INC_ENCODE_OUTPUT += _loc5_;
         APP_INC_ENCODE_ITERATOR = _loc1_ - 1;
      }
      _loc6_ = _loc6_ + 1;
      APP_INC_ENCODE_ITERATOR++;
      if(APP_INC_ENCODE_STRLEN <= APP_INC_ENCODE_ITERATOR)
      {
         return false;
      }
   }
   if(APP_INC_ENCODE_ITERATOR < APP_INC_ENCODE_STRLEN)
   {
      return true;
   }
   return false;
}
function EncodeOctalString_RLEo6c_Inc()
{
   var _loc6_ = 0;
   var _loc7_ = 40;
   var _loc4_ = APP_INC_ENCODE_SOURCE;
   var _loc3_;
   var _loc2_;
   var _loc1_;
   var _loc5_;
   while(_loc6_ < _loc7_)
   {
      _loc3_ = _loc4_.charAt(APP_INC_ENCODE_ITERATOR);
      _loc2_ = 0;
      _loc1_ = APP_INC_ENCODE_ITERATOR;
      while(_loc1_ < APP_INC_ENCODE_STRLEN && _loc2_ < RLEo6_MAX_RUN_LEN)
      {
         if(_loc4_.charAt(_loc1_) != _loc3_)
         {
            break;
         }
         _loc2_ = _loc2_ + 1;
         _loc1_ = _loc1_ + 1;
      }
      if(_loc2_ < RLEo6c_MIN_RUN_LEN)
      {
         APP_INC_ENCODE_OUTPUT += _loc3_;
      }
      else
      {
         _loc5_ = EncodeCharRun_RLEo6c(_loc3_,_loc2_);
         APP_INC_ENCODE_OUTPUT += _loc5_;
         APP_INC_ENCODE_ITERATOR = _loc1_ - 1;
      }
      _loc6_ = _loc6_ + 1;
      APP_INC_ENCODE_ITERATOR++;
      if(APP_INC_ENCODE_STRLEN <= APP_INC_ENCODE_ITERATOR)
      {
         return false;
      }
   }
   if(APP_INC_ENCODE_ITERATOR < APP_INC_ENCODE_STRLEN)
   {
      return true;
   }
   return false;
}
APP_INC_ENCODE_INTERVAL = null;
APP_INC_ENCODE_SOURCE = "";
APP_INC_ENCODE_OUTPUT = "";
APP_INC_ENCODE_CALLBACK = null;
APP_INC_ENCODE_STEP = 0;
APP_INC_ENCODE_STRLEN = 0;
APP_INC_ENCODE_ITERATOR = 0;
NinjaGame.prototype.DumpDemoData_Inc = function()
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
   return _loc6_;
};
