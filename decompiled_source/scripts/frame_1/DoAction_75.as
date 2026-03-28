function ThwompObject()
{
   this.name = "thwump";
   this.pos = new Vector2(141,14);
   this.anchor = new Vector2(91,82);
   this.fallgoal = new Vector2(98,74);
   this.goal = this.fallgoal;
   this.i = 6;
   this.j = 7;
   this.mini = 2;
   this.minj = 5;
   this.maxi = 8;
   this.maxj = 3;
   this.xw = tiles.xw * 0.75;
   this.yw = tiles.xw * 0.75;
   this.movedir = 1;
   this.fallspeed = tiles.xw * 0.35714285714285715;
   this.raisespeed = tiles.xw * 0.14285714285714285;
   this.speed = this.fallspeed;
   this.playerWasStanding = false;
   this.isMoving = false;
   this.dirEnum = AI_DIR_U;
   this.dir = new Vector2(1,0);
   objects.Register(this);
   this.mc = gfx.CreateSprite("debugThwompMC",LAYER_OBJECTS);
   this.mc._visible = false;
}
ThwompObject.prototype.Destruct = function()
{
   gfx.DestroyMC(this.mc);
   delete this.mc;
};
ThwompObject.prototype.Init = function(params)
{
   var _loc3_;
   var _loc4_;
   var _loc5_;
   var _loc6_;
   var _loc7_;
   var _loc8_;
   var _loc9_;
   if(params.length == 3)
   {
      this.pos.x = params[0];
      this.pos.y = params[1];
      this.anchor.x = this.pos.x;
      this.anchor.y = this.pos.y;
      objects.AddToGrid(this);
      objects.StartUpdate(this);
      objects.Moved(this);
      this.i = this.cell.i;
      this.j = this.cell.j;
      _loc3_ = params[2];
      _loc4_ = 0;
      this.dirEnum = _loc3_;
      if(_loc3_ == AI_DIR_U)
      {
         this.dir.x = 0;
         this.dir.y = -1;
         _loc5_ = this.pos.x;
         _loc6_ = this.pos.y;
         _loc7_ = this.cell.nU;
         while(_loc7_.ID == TID_EMPTY)
         {
            _loc6_ -= 2 * this.cell.yw;
            _loc7_ = _loc7_.nU;
         }
         _loc6_ -= this.yw;
         _loc6_ -= this.pos.y - this.cell.pos.y;
         this.mc._rotation = 180;
      }
      else if(_loc3_ == AI_DIR_D)
      {
         this.dir.x = 0;
         this.dir.y = 1;
         _loc5_ = this.pos.x;
         _loc6_ = this.pos.y;
         _loc7_ = this.cell.nD;
         while(_loc7_.ID == TID_EMPTY)
         {
            _loc6_ += 2 * this.cell.yw;
            _loc7_ = _loc7_.nD;
         }
         _loc6_ += this.yw;
         _loc6_ -= this.pos.y - this.cell.pos.y;
         this.mc._rotation = 0;
      }
      else if(_loc3_ == AI_DIR_L)
      {
         this.dir.x = -1;
         this.dir.y = 0;
         _loc5_ = this.pos.x;
         _loc6_ = this.pos.y;
         _loc7_ = this.cell.nL;
         while(_loc7_.ID == TID_EMPTY)
         {
            _loc5_ -= 2 * this.cell.xw;
            _loc7_ = _loc7_.nL;
         }
         _loc5_ -= this.xw;
         _loc5_ -= this.pos.x - this.cell.pos.x;
         this.mc._rotation = 90;
      }
      else if(_loc3_ == AI_DIR_R)
      {
         this.dir.x = 1;
         this.dir.y = 0;
         _loc5_ = this.pos.x;
         _loc6_ = this.pos.y;
         _loc7_ = this.cell.nR;
         while(_loc7_.ID == TID_EMPTY)
         {
            _loc5_ += 2 * this.cell.xw;
            _loc7_ = _loc7_.nR;
         }
         _loc5_ += this.xw;
         _loc5_ -= this.pos.x - this.cell.pos.x;
         this.mc._rotation = -90;
      }
      this.fallgoal.x = _loc5_;
      this.fallgoal.y = _loc6_;
      this.goal = this.fallgoal;
      this.i = this.cell.i;
      this.j = this.cell.j;
      this.mini = this.cell.i;
      this.minj = this.cell.j;
      _loc8_ = tiles.GetTile_S(_loc5_,_loc6_);
      this.maxi = _loc8_.i;
      this.maxj = _loc8_.j;
      if(this.dir.x < 0)
      {
         _loc9_ = this.mini;
         this.mini = this.maxi;
         this.maxi = _loc9_;
      }
      if(this.dir.y < 0)
      {
         _loc9_ = this.minj;
         this.minj = this.maxj;
         this.maxj = _loc9_;
      }
      this.Update = this.Update_Waiting;
      this.mc._xscale = 2 * this.xw;
      this.mc._yscale = 2 * this.yw;
      this.Draw();
      this.mc._visible = true;
   }
};
ThwompObject.prototype.UnInit = function()
{
   objects.RemoveFromGrid(this);
   objects.EndUpdate(this);
   objects.EndDraw(this);
};
ThwompObject.prototype.DumpInitData = function()
{
   var _loc2_ = "" + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y + OBJPARAM_SEPERATION_CHAR + this.dirEnum;
   return _loc2_;
};
ThwompObject.prototype.IdleAfterDeath = function()
{
   if(this.isMoving)
   {
      this.Update_Waiting = this.Update_Idle;
   }
   else
   {
      this.Update = this.Update_Idle;
   }
};
ThwompObject.prototype.Update_Idle = function()
{
};
ThwompObject.prototype.Draw = function()
{
   this.mc._x = this.pos.x;
   this.mc._y = this.pos.y;
};
ThwompObject.prototype.TestVsPlayer = function(guy)
{
   var _loc3_ = guy.pos;
   var _loc4_ = _loc3_.y - this.pos.y;
   var _loc5_ = Math.abs(_loc4_);
   var _loc6_ = this.yw + guy.yw - _loc5_;
   trace("FRAME " + game.tickCounter + " Distance to thwump; y " + _loc6_);
   var _loc7_;
   var _loc8_;
   var _loc9_;
   if(0 < _loc6_)
   {
      _loc7_ = _loc3_.x - this.pos.x;
      _loc8_ = Math.abs(_loc7_);
      _loc9_ = this.xw + guy.xw - _loc8_;
      if(0 < _loc9_)
      {
         if(_loc6_ < _loc9_)
         {
            if(_loc4_ < 0)
            {
               if(this.dir.y < 0)
               {
                  particles.SpawnZapThwompV(this.pos,this.xw,- this.yw,guy.pos);
                  game.KillPlayer(KILLTYPE_ELECTRIC,0,-8,guy.pos.x,guy.pos.y - 0.5 * guy.r,this);
               }
               else
               {
                  guy.ReportCollisionVsObject(0,- _loc6_,0,-1,this);
               }
            }
            else if(0 < this.dir.y)
            {
               particles.SpawnZapThwompV(this.pos,this.xw,this.yw,guy.pos);
               game.KillPlayer(KILLTYPE_ELECTRIC,0,6,guy.pos.x,guy.pos.y + 0.5 * guy.r,this);
            }
            else
            {
               guy.ReportCollisionVsObject(0,_loc6_,0,1,this);
            }
         }
         else if(_loc7_ < 0)
         {
            if(this.dir.x < 0)
            {
               particles.SpawnZapThwompH(this.pos,- this.xw,this.yw,guy.pos);
               game.KillPlayer(KILLTYPE_ELECTRIC,-8,-4,guy.pos.x - 0.5 * guy.r,guy.pos.y,this);
            }
            else
            {
               guy.ReportCollisionVsObject(- _loc9_,0,-1,0,this);
            }
         }
         else if(0 < this.dir.x)
         {
            particles.SpawnZapThwompH(this.pos,this.xw,this.yw,guy.pos);
            game.KillPlayer(KILLTYPE_ELECTRIC,8,-4,guy.pos.x + 0.5 * guy.r,guy.pos.y,this);
         }
         else
         {
            guy.ReportCollisionVsObject(_loc9_,0,1,0,this);
         }
      }
   }
};
ThwompObject.prototype.TestVsRagParticle = function(guy)
{
   var _loc3_ = guy.pos;
   var _loc4_ = _loc3_.y - this.pos.y;
   var _loc5_ = Math.abs(_loc4_);
   var _loc6_ = this.yw + guy.yw - _loc5_;
   var _loc7_;
   var _loc8_;
   var _loc9_;
   if(0 < _loc6_)
   {
      _loc7_ = _loc3_.x - this.pos.x;
      _loc8_ = Math.abs(_loc7_);
      _loc9_ = this.xw + guy.xw - _loc8_;
      if(0 < _loc9_)
      {
         if(_loc6_ < _loc9_)
         {
            if(_loc4_ < 0)
            {
               if(this.dir.y < 0)
               {
                  particles.SpawnZapThwompV(this.pos,this.xw,- this.yw,guy.pos);
                  guy.ReportCollisionVsObject(0,-8,0,-1,1);
                  player.RagDie(KILLTYPE_ELECTRIC);
               }
               else
               {
                  guy.ReportCollisionVsObject(0,- _loc6_,0,-1,0.3);
               }
            }
            else if(0 < this.dir.y)
            {
               particles.SpawnZapThwompV(this.pos,this.xw,this.yw,guy.pos);
               guy.ReportCollisionVsObject(0,6,0,1,1);
               player.RagDie(KILLTYPE_ELECTRIC);
            }
            else
            {
               guy.ReportCollisionVsObject(0,_loc6_,0,1,0.3);
            }
         }
         else if(_loc7_ < 0)
         {
            if(this.dir.x < 0)
            {
               particles.SpawnZapThwompH(this.pos,- this.xw,this.yw,guy.pos);
               guy.ReportCollisionVsObject(-8,-4,-1,0,1);
               player.RagDie(KILLTYPE_ELECTRIC);
            }
            else
            {
               guy.ReportCollisionVsObject(- _loc9_,0,-1,0,0.3);
            }
         }
         else if(0 < this.dir.x)
         {
            particles.SpawnZapThwompH(this.pos,this.xw,this.yw,guy.pos);
            guy.ReportCollisionVsObject(8,-4,1,0,1);
            player.RagDie(KILLTYPE_ELECTRIC);
         }
         else
         {
            guy.ReportCollisionVsObject(_loc9_,0,1,0,0.3);
         }
      }
   }
};
ThwompObject.prototype.StartFall = function()
{
   this.isMoving = true;
   this.speed = this.fallspeed;
   this.movedir = 1;
   this.goal = this.fallgoal;
   this.Update = this.Update_Moving;
   objects.StartDraw(this);
};
ThwompObject.prototype.StartRaise = function()
{
   this.isMoving = true;
   this.speed = this.raisespeed;
   this.movedir = -1;
   this.goal = this.anchor;
   this.Update = this.Update_Moving;
};
ThwompObject.prototype.StartWait = function()
{
   this.isMoving = false;
   this.Update = this.Update_Waiting;
   objects.EndDraw(this);
};
ThwompObject.prototype.Update_Waiting = function()
{
   var _loc2_;
   if(this.dir.x == 0)
   {
      if(Math.abs(this.pos.x - player.pos.x) < 2 * (this.xw + player.xw))
      {
         _loc2_ = player.cell.j;
         if(!(this.maxj < _loc2_ || _loc2_ < this.minj))
         {
            this.StartFall();
         }
      }
   }
   else if(Math.abs(this.pos.y - player.pos.y) < 2 * (this.yw + player.yw))
   {
      _loc2_ = player.cell.i;
      if(!(this.maxi < _loc2_ || _loc2_ < this.mini))
      {
         this.StartFall();
      }
   }
};
ThwompObject.prototype.Update_Moving = function()
{
   var _loc2_ = this.goal.x - this.pos.x;
   var _loc3_ = this.goal.y - this.pos.y;
   var _loc4_ = _loc2_ * _loc2_ + _loc3_ * _loc3_;
   if(_loc4_ < this.speed * this.speed)
   {
      this.pos.x = this.goal.x;
      this.pos.y = this.goal.y;
      if(this.movedir == 1)
      {
         this.StartRaise();
      }
      else
      {
         this.StartWait();
      }
   }
   else
   {
      this.pos.x += this.movedir * this.dir.x * this.speed;
      this.pos.y += this.movedir * this.dir.y * this.speed;
   }
   objects.Moved(this);
};
