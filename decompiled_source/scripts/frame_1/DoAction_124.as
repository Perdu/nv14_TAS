function DebugUpdateGameCode()
{
   var _loc3_ = input.getMousePos();
   var _loc5_;
   var _loc2_;
   var _loc1_;
   var _loc4_;
   if(player.isDead)
   {
      if(Key.isDown(16))
      {
         _loc5_ = input.getMouseDelta();
         player.raggy.Shove(_loc5_.x * 0.1,_loc5_.y * 0.1);
      }
      if(APP_KEY_TRIG && Key.isDown(32))
      {
         APP_KEY_TRIG = false;
         if(player.raggy.exploded == false)
         {
            player.raggy.Explode();
         }
         else
         {
            player.raggy.Unexplode();
         }
      }
      if(Key.isDown(17))
      {
         player.raggy.pList.h0.pos.x = player.raggy.pList.h0.oldpos.x = _loc3_.x;
         player.raggy.pList.h0.pos.y = player.raggy.pList.h0.oldpos.y = _loc3_.y;
      }
      if(APP_KEY_TRIG && Key.isDown(13))
      {
         APP_KEY_TRIG = false;
         player.pos.copy(_loc3_);
         player.oldpos.copy(_loc3_);
         player.Stand();
      }
   }
   else if(APP_KEY_TRIG && Key.isDown(13))
   {
      APP_KEY_TRIG = false;
      _loc2_ = player.pos.x - _loc3_.x;
      _loc1_ = player.pos.y - _loc3_.y;
      _loc4_ = Math.sqrt(_loc2_ * _loc2_ + _loc1_ * _loc1_);
      if(_loc4_ == 0)
      {
         game.KillPlayer(KILLTYPE_SOFTBULLET,_loc2_ * 10,_loc1_ * 10,player.pos.x,player.pos.y,null);
      }
      else
      {
         _loc2_ /= _loc4_;
         _loc1_ /= _loc4_;
         if(Key.isDown(32))
         {
            game.KillPlayer(KILLTYPE_EXPLOSIVE,_loc2_ * 10,_loc1_ * 10,player.pos.x,player.pos.y,null);
         }
         else
         {
            game.KillPlayer(KILLTYPE_SOFTBULLET,_loc2_ * 10,_loc1_ * 10,player.pos.x,player.pos.y,null);
         }
      }
   }
}
