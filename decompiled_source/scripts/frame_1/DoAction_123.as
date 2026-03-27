function DebugPointTest_Constant(x0, y0, x1, y1, n)
{
   if(n <= 0)
   {
      n = 1;
   }
   n += 1;
   var _loc6_ = x1 - x0;
   var _loc4_ = y1 - y0;
   var _loc5_ = Math.sqrt(_loc6_ * _loc6_ + _loc4_ * _loc4_);
   if(_loc5_ == 0)
   {
      if(QueryPointvsTileMap(x0,y0))
      {
         debug_rend.SetStyle(2,8921634,100);
         debug_rend.DrawPlus_S(x0,y0,4);
      }
      return undefined;
   }
   _loc6_ /= _loc5_;
   _loc4_ /= _loc5_;
   var _loc1_ = 0;
   var _loc3_ = x0;
   var _loc2_ = y0;
   while(_loc1_ < _loc5_)
   {
      if(QueryPointvsTileMap(_loc3_,_loc2_))
      {
         debug_rend.SetStyle(2,8921634,100);
         debug_rend.DrawPlus_S(_loc3_,_loc2_,4);
      }
      _loc1_ += n;
      _loc3_ = x0 + _loc1_ * _loc6_;
      _loc2_ = y0 + _loc1_ * _loc4_;
   }
   if(QueryPointvsTileMap(x1,y1))
   {
      debug_rend.SetStyle(2,8921634,100);
      debug_rend.DrawPlus_S(x1,y1,4);
   }
}
function DebugPointTest(x0, y0, x1, y1, n)
{
   if(n <= 0)
   {
      n = 1;
   }
   n += 1;
   var _loc5_;
   var _loc4_;
   var _loc1_;
   var _loc3_;
   var _loc2_ = 0;
   while(_loc2_ < n + 1)
   {
      _loc1_ = _loc2_ / n;
      _loc3_ = 1 - _loc1_;
      _loc5_ = _loc1_ * x0 + _loc3_ * x1;
      _loc4_ = _loc1_ * y0 + _loc3_ * y1;
      debug_rend.SetStyle(0,0,100);
      debug_rend.DrawPlus_S(_loc5_,_loc4_);
      if(QueryPointvsTileMap(_loc5_,_loc4_))
      {
         debug_rend.SetStyle(2,8921634,100);
         debug_rend.DrawCircle(new Vector2(_loc5_,_loc4_),4);
      }
      _loc2_ = _loc2_ + 1;
   }
}
