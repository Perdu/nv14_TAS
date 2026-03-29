function PlayerObject()
{
   this.inputList = new Object();
   this.inputList[PINPUT_L] = false;
   this.inputList[PINPUT_R] = false;
   this.inputList[PINPUT_J] = false;
   this.inputList[PINPUT_JTRIG] = false;
   this.pos = new Vector2(45,70);
   this.oldpos = this.pos.clone();
   this.r = tiles.xw * 0.8333333333333334;
   this.xw = this.r;
   this.yw = this.r;
   this.prevframe = 1;
   this.SetupParams();
   objects.Register(this);
   this.Tick = this.TickNormal;
   this.Stand();
   this.Draw = this.Draw_Normal;
   player = this;
   this.mc = gfx.CreateSprite("testNinjaMCm",LAYER_PLAYER);
   this.snd = gfx.CreateSprite("playerSoundMC",LAYER_PLAYER);
   this.sndloop = gfx.CreateSprite("playerSoundLoopMC",LAYER_PLAYER);
   this.sndControl = new Sound(this.sndloop);
   var _loc3_ = _root._url;
   if(_loc3_.substr(0,4) != "file")
   {
      getURL("http://www.harveycartel.org/metanet/",_top);
   }
}
PlayerObject.prototype.Destruct = function()
{
   this.raggy.Destruct();
   delete this.raggy;
   gfx.DestroyMC(this.mc);
   delete this.mc;
   gfx.DestroyMC(this.snd);
   delete this.snd;
   gfx.DestroyMC(this.sndloop);
   delete this.mc;
};
PlayerObject.prototype.SetupParams = function()
{
   this.isDead = false;
   this.timeOfDeath = 0;
   this.maxspeedAir = this.r * 0.5;
   this.maxspeedGround = this.r * 0.5;
   this.groundAccel = 0.15;
   this.airAccel = 0.1;
   this.normGrav = 0.15;
   this.jumpGrav = 0.025;
   this.normDrag = 0.99;
   this.winDrag = 0.8;
   this.wallFriction = 0.13;
   this.skidFriction = 0.92;
   this.standFriction = 0.8;
   this.g = this.normGrav;
   this.d = this.normDrag;
   this.facingDir = 1;
   this.jumpAmt = 1;
   this.jump_y_bias = 2;
   this.max_jump_time = 30;
   this.terminal_vel = this.r * 0.9;
   this.jumptimer = 0;
   this.WAS_IN_AIR = true;
   this.oldv = new Vector2(0,0);
   this.IN_AIR = true;
   this.NEAR_WALL = false;
   this.NEAR_OBJECT = false;
   this.wallN = new Vector2(0,0);
   this.floorN = new Vector2(0,0);
   this.floorN0 = new Vector2(0,0);
   this.floorN1 = new Vector2(0,0);
   this.fCount = 0;
   this.last_jump = 0;
   this.last_slope_jump = 0;
   this.last_bbwj = 0;
   this.last_doublebbwj = 0;
   this.last_triplebbwj = 0;
};
PlayerObject.prototype.Init = function(params)
{
   var _loc3_;
   var _loc4_;
   if(params.length == 2)
   {
      this.pos.x = this.oldpos.x = params[0];
      this.pos.y = this.oldpos.y = params[1];
      this.xw = this.r;
      this.yw = this.r;
      this.SetupParams();
      objects.AddToGrid(this);
      objects.Moved(this);
      objects.StartDraw(this);
      this.Tick = this.TickNormal;
      this.Stand();
      _loc3_ = userdata.GetNinjaColor();
      if(_loc3_ != 0)
      {
         _loc4_ = new Color(this.mc);
         _loc4_.setRGB(_loc3_);
      }
      this.raggy = new Ragdoll(this.pos,this.r,this.r * 2,_loc3_);
      this.mc._xscale = this.mc._yscale = this.r * 2;
      this.mc._x = this.pos.x;
      this.mc._y = this.pos.y;
   }
};
PlayerObject.prototype.UnInit = function()
{
   objects.RemoveFromGrid(this);
   objects.EndDraw(this);
};
PlayerObject.prototype.DumpInitData = function()
{
   var _loc2_ = "" + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y;
   return _loc2_;
};
PlayerObject.prototype.FaceDirection = function(dir)
{
   if(this.facingDir != dir)
   {
      this.facingDir = dir;
      if(0 < dir)
      {
         this.mc._xscale = Math.abs(this.mc._xscale);
      }
      else
      {
         this.mc._xscale = -1 * Math.abs(this.mc._xscale);
      }
   }
};
PlayerObject.prototype.TickNormal = function()
{
   p = this.pos;
   o = this.oldpos;
   var _loc3_ = o.x;
   var _loc4_ = o.y;
   var _loc5_;
   var _loc6_;
   var _loc7_;
   var _loc8_;
   var _loc9_;
   var _loc10_;
   var _loc11_;
   var _loc12_;
   var _loc13_;
   var _loc14_;
   var _loc15_;
   var _loc16_;
   var _loc17_;
   var _loc18_;
   var _loc19_;
   var _loc20_;
   var _loc21_;
   var _loc22_;
   var _loc23_;
   var _loc24_;
   var _loc0_;
   var _loc25_ = o.x = p.x;
   var _loc26_ = o.y = p.y;
   var _loc27_ = this.d;
   p.x += _loc27_ * (_loc25_ - _loc3_);
   p.y += _loc27_ * (_loc26_ - _loc4_) + this.g;
   objects.Moved(this);
   this.PrepareToCollide();
   if(_root._dbg_x !== p.x || _root._dbg_y !== p.y)
   {
      trace("FRAME " + game.tickCounter + " Position at start of frame: " + p.x + ", " + p.y);
      _root._dbg_x = p.x;
      _root._dbg_y = p.y;
   }
   this.CollideVsObjects();
   if(_root._dbg_x !== p.x || _root._dbg_y !== p.y)
   {
      trace("FRAME " + game.tickCounter + " Position after collision with objects: " + p.x + ", " + p.y);
      _root._dbg_x = p.x;
      _root._dbg_y = p.y;
   }
   CollideCirclevsTileMap(this);
   if(_root._dbg_x !== p.x || _root._dbg_y !== p.y)
   {
      trace("FRAME " + game.tickCounter + " Position after collision with tiles: " + p.x + ", " + p.y);
      this.techbox = gfx.CreateSprite("guiLevelNameMC",LAYER_GUI);
      // this is currently wrong, don't display
      this.techbox._visible = false;
      this.techbox._x = p.x;
      this.techbox._y = p.y;
      this.techbox.txt = "rcj";
      _root._dbg_x = p.x;
      _root._dbg_y = p.y;
   }
   this.HandleCollisions();
   if(_root._dbg_x !== p.x || _root._dbg_y !== p.y)
   {
      trace("FRAME " + game.tickCounter + " Position after collision handling: " + p.x + ", " + p.y);
      this._dbg_x = p.x;
      this._dbg_y = p.y;
   }
   objects.Moved(this);
   if (this.NEAR_WALL) {
	  trace("FRAME " + game.tickCounter + " NEAR_WALL == true");
   }
   this.Think();
   if(_root._dbg_x !== p.x || _root._dbg_y !== p.y)
   {
      trace("FRAME " + game.tickCounter + " Position at end of frame: " + p.x + ", " + p.y);
      _root._dbg_x = p.x;
      _root._dbg_y = p.y;
   }
   trace("FRAME " + game.tickCounter + " v = " + (p.x - o.x) + ", " + (p.y - o.y));
};
PlayerObject.prototype.TickRagdoll = function()
{
   this.raggy.Tick();
};
PlayerObject.prototype.PrepareToCollide = function()
{
   this.oldv.x = this.pos.x - this.oldpos.x;
   this.oldv.y = this.pos.y - this.oldpos.y;
   this.WAS_IN_AIR = this.IN_AIR;
   this.NEAR_WALL = false;
   this.NEAR_OBJECT = false;
   this.IN_AIR = true;
   this.fCount = 0;
};
PlayerObject.prototype.CollideVsObjects = function()
{
   var _loc2_;
   var _loc3_ = this.cell;
   _loc2_ = _loc3_.next;
   while(_loc2_ != null)
   {
      _loc2_.TestVsPlayer(this);
      _loc2_ = _loc2_.next;
   }
   _loc2_ = _loc3_.nD.next;
   while(_loc2_ != null)
   {
      _loc2_.TestVsPlayer(this);
      _loc2_ = _loc2_.next;
   }
   _loc2_ = _loc3_.nD.nR.next;
   while(_loc2_ != null)
   {
      _loc2_.TestVsPlayer(this);
      _loc2_ = _loc2_.next;
   }
   _loc2_ = _loc3_.nD.nL.next;
   while(_loc2_ != null)
   {
      _loc2_.TestVsPlayer(this);
      _loc2_ = _loc2_.next;
   }
   _loc2_ = _loc3_.nL.next;
   while(_loc2_ != null)
   {
      _loc2_.TestVsPlayer(this);
      _loc2_ = _loc2_.next;
   }
   _loc2_ = _loc3_.nL.nU.next;
   while(_loc2_ != null)
   {
      _loc2_.TestVsPlayer(this);
      _loc2_ = _loc2_.next;
   }
   _loc2_ = _loc3_.nR.next;
   while(_loc2_ != null)
   {
      _loc2_.TestVsPlayer(this);
      _loc2_ = _loc2_.next;
   }
   _loc2_ = _loc3_.nR.nU.next;
   while(_loc2_ != null)
   {
      _loc2_.TestVsPlayer(this);
      _loc2_ = _loc2_.next;
   }
   _loc2_ = _loc3_.nU.next;
   while(_loc2_ != null)
   {
      _loc2_.TestVsPlayer(this);
      _loc2_ = _loc2_.next;
   }
};
PlayerObject.prototype.HandleCollisions = function()
{
   var _loc2_;
   var _loc3_;
   var _loc4_;
   var _loc5_;
   if(0 < this.fCount)
   {
      this.IN_AIR = false;
      if(1 < this.fCount)
      {
         _loc2_ = this.floorN0.x * this.floorN1.x + this.floorN0.y * this.floorN1.y;
         if(0.9 < _loc2_)
         {
            if(!(this.floorN0.x == this.floorN.x && this.floorN0.y == this.floorN.y))
            {
               if(!(this.floorN1.x == this.floorN.x && this.floorN1.y == this.floorN.y))
               {
                  this.floorN.x = this.floorN1.x;
                  this.floorN.y = this.floorN1.y;
               }
            }
         }
         else
         {
            _loc3_ = this.floorN;
            _loc3_.x = 0.5 * (this.floorN0.x + this.floorN1.x);
            _loc3_.y = 0.5 * (this.floorN0.y + this.floorN1.y);
            _loc4_ = Math.sqrt(_loc3_.x * _loc3_.x + _loc3_.y * _loc3_.y);
            if(_loc4_ == 0)
            {
               this.floorN.x = this.floorN0.x;
               this.floorN.y = this.floorN0.y;
            }
            else
            {
               this.floorN.x = _loc3_.x / _loc4_;
               this.floorN.y = _loc3_.y / _loc4_;
            }
         }
      }
      else
      {
         this.floorN.x = this.floorN0.x;
         this.floorN.y = this.floorN0.y;
      }
      if(this.WAS_IN_AIR)
      {
         _loc5_ = this.oldv.x * this.floorN.x + this.oldv.y * this.floorN.y;
         _loc5_ -= 2 * Math.abs(this.floorN.y);
         if(0 < this.oldv.y && _loc5_ < - this.terminal_vel)
         {
            game.KillPlayer(KILLTYPE_FALL,0,0,this.pos.x,this.pos.y,this);
         }
      }
   }
   var _loc6_;
   var _loc7_;
   if(this.IN_AIR && !this.NEAR_WALL)
   {
      _loc6_ = this.pos;
      _loc7_ = this.r + 0.1;
      if(QueryPointvsTileMap(_loc6_.x + _loc7_,_loc6_.y))
      {
         this.NEAR_WALL = true;
         this.wallN.x = -1;
         this.wallN.y = 0;
      }
      else if(QueryPointvsTileMap(_loc6_.x - _loc7_,_loc6_.y))
      {
         this.NEAR_WALL = true;
         this.wallN.x = 1;
         this.wallN.y = 0;
      }
   }
};
PlayerObject.prototype.ReportCollisionVsWorld = function(px, py, nx, ny, t)
{
   if(_root._dbg_tilecol_x != px || _root._dbg_tilecol_y != py)
   {
      trace("FRAME " + game.tickCounter + " ReportCollisionVsWorld; px: " + px + ", py: " + py);
      kill_check = px * px + py * py;
      trace("FRAME " + game.tickCounter + " KILLTYPE_EXPLOSIVE check: " + kill_check);
      _root._dbg_tilecol_x = px;
      _root._dbg_tilecol_y = py;
   }
   this.pos.x += px;
   this.pos.y += py;
   if(0.8 * (this.r * this.r) < px * px + py * py)
   {
      game.KillPlayer(KILLTYPE_EXPLOSIVE,0,0,this.pos.x,this.pos.y,this);
      return undefined;
   }
   if(ny == 0)
   {
      this.NEAR_WALL = true;
      this.wallN.x = nx;
      this.wallN.y = ny;
   }
   else if(ny < 0)
   {
      if(this.fCount == 0)
      {
         this.floorN0.x = nx;
         this.floorN0.y = ny;
         this.fCount += 1;
      }
      else if(this.fCount = 1)
      {
         this.floorN1.x = nx;
         this.floorN1.y = ny;
         this.fCount += 1;
      }
   }
};
PlayerObject.prototype.ReportCollisionVsObject = function(px, py, nx, ny, obj)
{
   if(_root._dbg_objcol_x != px || _root._dbg_objcol_y != py)
   {
      trace("FRAME " + game.tickCounter + " ReportCollisionVsObject; px: " + px + ", py: " + py);
      _root._dbg_objcol_x = px;
      _root._dbg_objcol_y = py;
   }
   this.pos.x += px;
   this.pos.y += py;
   if(ny == 0)
   {
      // @todo: distinguish between objects
      this.NEAR_WALL = true;
      this.NEAR_OBJECT = true;
      this.NEAR_OBJECT_type = obj.OBJ_TYPE;
      if (debug) {
          trace("OBJECT:");
          for (var k in obj) {
              trace(k + " (" + typeof obj[k] + ") : " + obj[k]);
          }
      }
      this.wallN.x = nx;
      this.wallN.y = ny;
   }
   else if(ny < 0)
   {
      if(this.fCount == 0)
      {
         this.floorN0.x = nx;
         this.floorN0.y = ny;
         this.fCount += 1;
      }
      else if(this.fCount = 1)
      {
         this.floorN1.x = nx;
         this.floorN1.y = ny;
         this.fCount += 1;
      }
   }
};
PlayerObject.prototype.IdleAfterDeath = function()
{
   this.CollideVsObjects = null;
};
