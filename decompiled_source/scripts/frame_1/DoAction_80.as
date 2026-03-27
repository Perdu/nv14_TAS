function DroneObject()
{
   this.name = "drone";
   this.pos = new Vector2(41,14);
   this.r = tiles.xw * 0.75;
   this.dirList = new Object();
   this.dirList[AI_DIR_R] = new Vector2(1,0);
   this.dirList[AI_DIR_D] = new Vector2(0,1);
   this.dirList[AI_DIR_L] = new Vector2(-1,0);
   this.dirList[AI_DIR_U] = new Vector2(0,-1);
   this.curDir = AI_DIR_R;
   this.curDirV = this.dirList[this.curDir];
   this.goal = new Vector2(54,85);
   this.speed = tiles.xw * 0.07142857142857142;
   this.curRot = 0;
   this.isChaser = false;
   this.ischasing = false;
   this.waschasing = false;
   this.ai_counter = 0;
   this.ai_counter2 = 0;
   this.view = new Vector2(9,4);
   this.fireDelayTimer = 0;
   this.targ = new Vector2(4,5);
   this.targ2 = new Vector2(5,7);
   this.targ3 = new Vector2(3,6);
   this.prefireDelay = 0;
   this.postfireDelay = 0;
   this.isFiring = false;
   this.laserPrefireDelay = 30;
   this.laserPostfireDelay = 40;
   this.laserRate = 80;
   this.laserTimer = 0;
   this.laserLen = 7;
   this.chaingunPrefireDelay = 35;
   this.chaingunPostfireDelay = 60;
   this.chaingunMaxNum = 8;
   this.chaingunCurNum = 0;
   this.chaingunRate = 6;
   this.chaingunTimer = 0;
   this.chaingunSpread = 0.3;
   objects.Register(this);
   this.mc = gfx.CreateSprite("debugDroneMC",LAYER_OBJECTS);
   this.mc._visible = false;
   this.eyeMC = this.mc.attachMovie("debugDroneEyeMC","drone" + this.UID,this.UID);
   this.snd = new Sound(this.mc);
}
DroneObject.prototype.Destruct = function()
{
   gfx.DestroyMC(this.mc);
   gfx.DestroyMC(this.beamMC);
   gfx.DestroyMC(this.blastMC);
   gfx.DestroyMC(this.gunMC);
   gfx.DestroyMC(this.eyeMC);
   delete this.mc;
   delete this.beamMC;
   delete this.blastMC;
   delete this.eyeMC;
   delete this.snd;
};
DroneObject.prototype.Init = function(params)
{
   if(params.length == 6)
   {
      this.pos.x = params[0];
      this.pos.y = params[1];
      this.curDir = params[5];
      this.SetDir(this.curDir);
      objects.AddToGrid(this);
      objects.StartUpdate(this);
      objects.Moved(this);
      this.pos.x = this.goal.x = this.cell.pos.x;
      this.pos.y = this.goal.y = this.cell.pos.y;
      this.SetupDroneType(params[2],Boolean(params[3]),params[4]);
      this.mc._xscale = this.mc._yscale = 2 * this.r;
   }
};
DroneObject.prototype.UnInit = function()
{
   objects.RemoveFromGrid(this);
   objects.EndUpdate(this);
   objects.EndThink(this);
   objects.EndDraw(this);
};
DroneObject.prototype.DumpInitData = function()
{
   var _loc2_ = "" + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y + OBJPARAM_SEPERATION_CHAR + this.DRONEMOVE + OBJPARAM_SEPERATION_CHAR + Number(this.isChaser) + OBJPARAM_SEPERATION_CHAR + this.DRONEWEAP + OBJPARAM_SEPERATION_CHAR + this.curDir;
   return _loc2_;
};
DroneObject.prototype.IdleAfterDeath = function()
{
   if(this.isChaser)
   {
      this.Chase = this.Chase_NoSearch;
      this.ischasing = false;
   }
   this.Think = null;
   if(this.isFiring)
   {
      this.StopFiring();
   }
};
DroneObject.prototype.SetupDroneType = function(movetype, isChaser, weaptype)
{
   this.mc.clear();
   this.DRONEMOVE = movetype;
   this.DRONEWEAP = weaptype;
   this.isChaser = isChaser;
   if(movetype == DRONEMOVE_SURFACEFOLLOW_CW)
   {
      this.GetNewGoal = this.GetNewGoal_Simple;
      this.moveList = MoveList_SurfaceCW;
   }
   else if(movetype == DRONEMOVE_SURFACEFOLLOW_CCW)
   {
      this.GetNewGoal = this.GetNewGoal_Simple;
      this.moveList = MoveList_SurfaceCCW;
   }
   else if(movetype == DRONEMOVE_WANDER_CW)
   {
      this.GetNewGoal = this.GetNewGoal_Simple;
      this.moveList = MoveList_ChuChuCW;
   }
   else if(movetype == DRONEMOVE_WANDER_CCW)
   {
      this.GetNewGoal = this.GetNewGoal_Simple;
      this.moveList = MoveList_ChuChuCCW;
   }
   else if(movetype == DRONEMOVE_WANDER_ALTERNATING)
   {
      this.GetNewGoal = this.GetNewGoal_ChuChuAlternating;
   }
   else if(movetype == DRONEMOVE_WANDER_RANDOM)
   {
      this.GetNewGoal = this.GetNewGoal_ChuChuRandom;
   }
   if(weaptype == DRONEWEAP_ZAP)
   {
      if(isChaser)
      {
         this.Chase = this.Chase_AxisSearch;
         this.isChaser = true;
         this.ischasing = false;
         this.mc.gotoAndStop("zapdrone_chaseidle");
      }
      else
      {
         this.Chase = this.Chase_NoSearch;
         this.isChaser = false;
         this.ischasing = false;
         this.mc.gotoAndStop("zapdrone_move");
      }
      this.name = "zap drone";
      this.weaptype = DRONEWEAP_ZAP;
      this.speed *= 2;
      this.TestVsPlayer = this.TestVsPlayer_Zap;
      this.TestVsRagParticle = this.TestVsRagParticle_Zap;
   }
   else if(weaptype == DRONEWEAP_LASER)
   {
      this.Chase = this.Chase_NoSearch;
      this.isChaser = false;
      this.ischasing = false;
      this.name = "laser drone";
      this.weaptype = DRONEWEAP_LASER;
      this.speed *= 0.5;
      this.Think = this.Think_TargetPlayer;
      this.Fire = this.Fire_Laser;
      this.StartFiring = this.StartFiring_Laser;
      this.StopFiring = this.StopFiring_Laser;
      this.Update_PreFire = this.Update_PreFire_Laser;
      this.Update_PostFire = this.Update_PostFire_Laser;
      this.prefireDelay = this.laserPrefireDelay;
      this.postfireDelay = this.laserPostfireDelay;
      objects.StartThink(this);
      this.mc.gotoAndStop("laserdrone_move");
      this.beamdx = 0;
      this.beamdy = 0;
      this.beamMC = gfx.CreateEmptySprite(LAYER_OBJECTS);
      this.beamMC._visible = false;
      this.blastMC = gfx.CreateSprite("debugLaserBlastMC",LAYER_OBJECTS);
      this.blastMC._visible = false;
   }
   else if(weaptype == DRONEWEAP_CHAINGUN)
   {
      this.Chase = this.Chase_NoSearch;
      this.isChaser = false;
      this.ischasing = false;
      this.name = "chaingun drone";
      this.weaptype = DRONEWEAP_CHAINGUN;
      this.speed *= 0.75;
      this.Think = this.Think_TargetPlayer;
      this.Fire = this.Fire_Chaingun;
      this.StartFiring = this.StartFiring_Chaingun;
      this.StopFiring = this.StopFiring_Chaingun;
      this.Update_PreFire = this.Update_PreFire_Chaingun;
      this.Update_PostFire = this.Update_PostFire_Chaingun;
      this.prefireDelay = this.chaingunPrefireDelay;
      this.postfireDelay = this.chaingunPostfireDelay;
      objects.StartThink(this);
      this.chainturretRot = 0;
      this.mc.gotoAndStop("chaingundrone_move");
      this.eyeMC = this.mc.attachMovie("debugChainTurretMC","chainturret" + this.UID,this.UID);
   }
   this.Draw();
   this.mc._visible = true;
   this.Update = this.Update_Move;
   objects.StartDraw(this);
};
DroneObject.prototype.Draw = function()
{
   this.mc._x = this.pos.x;
   this.mc._y = this.pos.y;
   var _loc2_ = this.curRot - this.eyeMC._rotation;
   this.eyeMC._rotation += 0.3 * _loc2_;
};
DroneObject.prototype.Update_Move = function()
{
   this.ai_counter = this.ai_counter + 1;
   var _loc4_ = this.goal.x - this.pos.x;
   var _loc3_ = this.goal.y - this.pos.y;
   var _loc5_ = _loc4_ * _loc4_ + _loc3_ * _loc3_;
   var _loc2_;
   if(_loc5_ < this.speed * this.speed)
   {
      this.pos.x = this.goal.x;
      this.pos.y = this.goal.y;
      if(this.Chase())
      {
         this.ischasing = true;
         this.mc.gotoAndPlay("zapdrone_chaseactive");
      }
      else
      {
         this.SetDir(this.GetNewGoal());
         this.ischasing = false;
      }
   }
   else
   {
      _loc2_ = this.speed;
      if(this.ischasing)
      {
         _loc2_ *= 2;
      }
      this.pos.x += this.curDirV.x * _loc2_;
      this.pos.y += this.curDirV.y * _loc2_;
   }
   objects.Moved(this);
};
