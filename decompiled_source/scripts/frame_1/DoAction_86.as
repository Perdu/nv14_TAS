PlayerObject.prototype.Jump = function(x, y)
{
   this.ExitState();
   this.ExitState = this.ExitJump;
   this.curState = PSTATE_JUMPING;
   this.g = this.jumpGrav;
   var _loc4_ = this.pos.x - this.oldpos.x;
   var _loc5_ = this.pos.y - this.oldpos.y;
   if(_loc4_ * x < 0)
   {
      this.oldpos.x = this.pos.x;
   }
   if(_loc5_ * y < 0)
   {
      this.oldpos.y = this.pos.y;
   }
   this.pos.x += x * this.jumpAmt;
   this.pos.y += y * (this.jumpAmt + this.jump_y_bias);
   this.jumptimer = 0;
   this.mc._rotation = 0;
   this.Render = this.RenderInAir;
   this.snd.gotoAndPlay("jump");
   if(debug)
   {
      trace("jumped");
   }
};
PlayerObject.prototype.ExitJump = function()
{
   this.g = this.normGrav;
};
PlayerObject.prototype.Fall = function()
{
   this.ExitState();
   this.ExitState = this.ExitFall;
   this.curState = PSTATE_FALLING;
   this.Render = this.RenderInAir;
};
PlayerObject.prototype.ExitFall = function()
{
};
PlayerObject.prototype.Wallslide = function()
{
   this.ExitState();
   this.ExitState = this.ExitWallslide;
   this.curState = PSTATE_WALLSLIDING;
   this.FaceDirection(- this.wallN.x);
   this.mc._rotation = 0;
   this.Render = this.RenderWallSlide;
   this.mc.gotoAndStop("WALLSLIDE");
   this.sndControl.setVolume(0);
   this.sndloop.gotoAndPlay("wallslide_start");
};
PlayerObject.prototype.ExitWallslide = function()
{
   this.sndloop.gotoAndPlay("wallslide_stop");
   this.sndControl.setVolume(100);
};
PlayerObject.prototype.Skid = function()
{
   this.ExitState();
   this.ExitState = this.ExitSkid;
   this.curState = PSTATE_SKIDDING;
   this.Render = this.RenderStatic_Ground;
   this.mc.gotoAndStop("SKID");
   this.sndControl.setVolume(100);
   this.sndloop.gotoAndPlay("skid_start");
};
PlayerObject.prototype.ExitSkid = function()
{
   this.sndloop.gotoAndPlay("skid_stop");
   this.sndControl.setVolume(100);
};
PlayerObject.prototype.Run = function(dirX)
{
   this.ExitState();
   this.ExitState = this.ExitRun;
   this.curState = PSTATE_RUNNING;
   this.Render = this.RenderRun;
   this.mc.gotoAndStop("RUN");
   this.runanimleftovers = 0;
};
PlayerObject.prototype.ExitRun = function()
{
};
PlayerObject.prototype.Stand = function()
{
   this.ExitState();
   this.ExitState = this.ExitStand;
   this.curState = PSTATE_STANDING;
   this.Render = this.RenderStatic_Ground;
   this.mc.gotoAndPlay("STAND");
};
PlayerObject.prototype.ExitStand = function()
{
};
PlayerObject.prototype.Launch = function(x, y)
{
   this.oldpos.x = this.pos.x;
   this.oldpos.y = this.pos.y;
   this.pos.x += x;
   this.pos.y += y;
   this.Fall();
};
PlayerObject.prototype.Die = function(x, y, px, py, KTYPE)
{
   var _loc7_ = Math.random() < 0.5;
   if(KTYPE == KILLTYPE_EXPLOSIVE)
   {
      if(_loc7_ == false)
      {
         this.snd.gotoAndPlay("explode1");
      }
      else
      {
         this.snd.gotoAndPlay("explode2");
      }
   }
   else if(KTYPE == KILLTYPE_FALL)
   {
      this.snd.gotoAndPlay("fall");
   }
   else if(KTYPE == KILLTYPE_LASER)
   {
      this.snd.gotoAndPlay("laser");
   }
   else if(KTYPE == KILLTYPE_ELECTRIC)
   {
      if(_loc7_ == false)
      {
         this.snd.gotoAndPlay("zap1");
      }
      else
      {
         this.snd.gotoAndPlay("zap1");
      }
   }
   else if(_loc7_ == false)
   {
      this.snd.gotoAndPlay("shot1");
   }
   else
   {
      this.snd.gotoAndPlay("shot2");
   }
   particles.SpawnBloodSpurt(px,py,x,y,6 + Math.floor(Math.random() * 8));
   this.ExitState();
   this.ExitState = this.ExitDie;
   this.curState = PSTATE_RAGDOLL;
   this.Tick = this.TickRagdoll;
   this.Think = null;
   this.Draw = this.Draw_Ragdoll;
   this.mc._visible = false;
   this.isDead = true;
   this.timeOfDeath = game.GetTime();
   var _loc8_ = this.pos.x - this.oldpos.x;
   var _loc9_ = this.pos.y - this.oldpos.y;
   this.raggy.Activate();
   this.raggy.MimicMC(_loc8_,_loc9_,this.mc,this.facingDir,this.prevframe);
   var _loc10_;
   var _loc11_;
   var _loc12_;
   var _loc13_;
   var _loc14_;
   if(KTYPE != KILLTYPE_FALL)
   {
      if(!this.IN_AIR)
      {
         _loc10_ = this.floorN.x * x + this.floorN.y * y;
         if(_loc10_ < 0)
         {
            _loc11_ = _loc10_ * this.floorN.x;
            _loc12_ = _loc10_ * this.floorN.y;
            _loc13_ = x - _loc11_;
            _loc14_ = y - _loc12_;
            static_rend.SetStyle(0,2237064,100);
            static_rend.DrawLine_S(this.pos.x,this.pos.y,this.pos.x + _loc11_,this.pos.y + _loc12_);
            static_rend.SetStyle(0,8921634,100);
            static_rend.DrawLine_S(this.pos.x,this.pos.y,this.pos.x + _loc13_,this.pos.y + _loc14_);
            x -= _loc11_ * 0.85;
            y -= _loc12_ * 0.85;
            x += _loc13_ * 0.4;
            y += _loc14_ * 0.4;
         }
      }
      if(this.NEAR_WALL)
      {
         _loc10_ = this.wallN.x * x + this.wallN.y * y;
         if(_loc10_ < 0)
         {
            _loc11_ = _loc10_ * this.wallN.x;
            _loc12_ = _loc10_ * this.wallN.y;
            _loc13_ = x - _loc11_;
            _loc14_ = y - _loc12_;
            static_rend.SetStyle(0,2237064,100);
            static_rend.DrawLine_S(this.pos.x,this.pos.y,this.pos.x + _loc11_,this.pos.y + _loc12_);
            static_rend.SetStyle(0,8921634,100);
            static_rend.DrawLine_S(this.pos.x,this.pos.y,this.pos.x + _loc13_,this.pos.y + _loc14_);
            x -= _loc11_ * 0.85;
            y -= _loc12_ * 0.85;
            x += _loc13_ * 0.4;
            y += _loc14_ * 0.4;
         }
      }
      this.raggy.Shove_VertBias(x,y,px,py,this.pos.y,this.r);
   }
   this.TickRagdoll();
};
PlayerObject.prototype.RagDie = function(KTYPE)
{
   var _loc3_ = Math.random() < 0.5;
   if(KTYPE == KILLTYPE_EXPLOSIVE)
   {
      this.raggy.chunkAccumulator += Math.random() * 0.6;
      if(!this.raggy.exploded && Math.random() < this.raggy.chunkAccumulator)
      {
         this.raggy.Explode();
         if(_loc3_ == false)
         {
            this.snd.gotoAndPlay("explode1");
         }
         else
         {
            this.snd.gotoAndPlay("explode2");
         }
      }
      else if(_loc3_ == false)
      {
         this.snd.gotoAndPlay("shot1");
      }
      else
      {
         this.snd.gotoAndPlay("shot2");
      }
   }
   else if(KTYPE == KILLTYPE_FALL)
   {
      this.snd.gotoAndPlay("fall");
   }
   else if(KTYPE == KILLTYPE_LASER)
   {
      this.snd.gotoAndPlay("laser");
   }
   else if(KTYPE == KILLTYPE_ELECTRIC)
   {
      if(_loc3_ == false)
      {
         this.snd.gotoAndPlay("zap1");
      }
      else
      {
         this.snd.gotoAndPlay("zap1");
      }
   }
   else if(_loc3_ == false)
   {
      this.snd.gotoAndPlay("shot1");
   }
   else
   {
      this.snd.gotoAndPlay("shot2");
   }
};
PlayerObject.prototype.ExitDie = function()
{
   if(this.raggy.exploded)
   {
      this.raggy.Unexplode();
   }
   this.raggy.Deactivate();
   this.isDead = false;
   this.timeOfDeath = 0;
   this.Tick = this.TickNormal;
   this.Think = PlayerObject.prototype.Think;
   this.mc._visible = true;
   this.Draw = this.Draw_Normal;
};
PlayerObject.prototype.Celebrate = function()
{
   this.ExitState();
   this.ExitState = this.ExitCelebrate;
   this.curState = PSTATE_CELEBRATING;
   this.Think = this.ThinkCelebrate;
   this.celeb_wasinair = this.IN_AIR;
};
PlayerObject.prototype.ExitCelebrate = function()
{
   this.d = this.normDrag;
   this.Think = PlayerObject.prototype.Think;
};
PlayerObject.prototype.techwrite = function(name, color, position_x, position_y, durationFrames)
{
    if (color == undefined) color = 0xFF000000;
    if (durationFrames == undefined) durationFrames = 60;

    var techbox = gfx.CreateSprite("guiLevelNameMC", LAYER_GUI);
    techbox._x = p.x + position_x;
    techbox._y = p.y + position_y;
    techbox.txt = name;

    for (var k in techbox) {
        if (typeof techbox[k] == "object") {
           // The TextField
           techbox[k].textColor = color;
//           techbox[k].multiline = true;
//           techbox[k].wordWrap = true;
           break;
        }
    }

    var frameRate = 40;
    var intervalMs = 1000 / frameRate;

    // Frames to wait before starting fade
    var visibleFrames = 20;
    var fadeFrames = durationFrames - visibleFrames;

    techbox._alpha = 100;
    var currentFrame = 0;

    var self = techbox;
    var fadeInterval = setInterval(function() {
        currentFrame++;

        if (currentFrame > visibleFrames) {
            // Start fading
            var fadeProgress = currentFrame - visibleFrames;
            self._alpha = 100 - (fadeProgress / fadeFrames) * 100;
        }

        if (currentFrame >= durationFrames) {
            clearInterval(fadeInterval);
            self.removeMovieClip();
        }
    }, intervalMs);
};

PlayerObject.prototype.simple_write = function(name, color)
{
    if (color == undefined) color = 0xFF000000;

    var techbox = gfx.CreateSprite("guiLevelNameMC", LAYER_GUI);
    techbox._x = p.x;
    techbox._y = p.y - 10;
    techbox.txt = name;

    // Set color
    for (var k in techbox) {
        if (typeof techbox[k] == "object") {
            techbox[k].textColor = color;
            break;
        }
    }

    // Remove after ~1 frame (safe delay)
    var delay = 25; // ~1 frame at 40fps

    var self = techbox;
    var id = setInterval(function() {
        clearInterval(id);
        self.removeMovieClip();
    }, delay);
};
