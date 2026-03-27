function TestDoorObject()
{
   this.name = "door";
   this.vert = 0;
   this.doorI = 2;
   this.doorJ = 3;
   this.doorpos = new Vector2(29,19);
   this.doorsize = 10;
   this.doorcell_N = 0;
   this.doorcell_P = 0;
   this.pos = new Vector2(32,84);
   this.r = tiles.xw * 0.8333333333333334;
   this.deltaI = 0;
   this.deltaJ = 0;
   this.isOpen = false;
   this.doortimer = 0;
   this.maxtimer = 5;
   this.isLocked = false;
   this.isTrap = false;
   this.openStateFront = EID_OFF;
   this.openStateBack = EID_OFF;
   objects.Register(this);
   this.mc = gfx.CreateSprite("debugTestDoorMC",LAYER_WALLS);
   this.mc._visible = false;
   this.mc.gotoAndStop("closed_Trek");
   this.trigMC = gfx.CreateSprite("debugDoorTriggerMC",LAYER_WALLS);
   this.trigMC.gotoAndStop("exit_closed");
   this.trigMC._visible = false;
}
TestDoorObject.prototype.Destruct = function()
{
   gfx.DestroyMC(this.mc);
   delete this.mc;
   gfx.DestroyMC(this.trigMC);
   delete this.trigMC;
};
TestDoorObject.prototype.Init = function(params)
{
   if(params.length == 9)
   {
      this.deltaI = params[7];
      this.deltaJ = params[8];
      this.doorI = params[4] + this.deltaI;
      this.doorJ = params[5] + this.deltaJ;
      this.vert = params[2];
      this.isTrap = Boolean(params[3]);
      this.isLocked = Boolean(params[6]);
      this.doorcell_N = tiles.GetTile_I(this.doorI,this.doorJ);
      this.doorpos.x = this.doorcell_N.pos.x;
      this.doorpos.y = this.doorcell_N.pos.y;
      if(this.vert == 1)
      {
         this.doorpos.y += this.doorcell_N.yw;
         this.doorsize = this.doorcell_N.xw;
         this.doorcell_P = this.doorcell_N.nD;
         this.openStateFront = this.doorcell_N.eD;
         this.openStateBack = this.doorcell_P.eU;
      }
      else
      {
         this.doorpos.x += this.doorcell_N.xw;
         this.doorsize = this.doorcell_N.yw;
         this.doorcell_P = this.doorcell_N.nR;
         this.openStateFront = this.doorcell_N.eR;
         this.openStateBack = this.doorcell_P.eL;
      }
      if(this.isLocked)
      {
         this.openFrameLabel = "opening_Lock";
         this.closedFrameLabel = "closed_Lock";
         this.mc.gotoAndStop("closed_Lock");
         this.pos.x = params[0];
         this.pos.y = params[1];
         this.r = tiles.xw * 0.4166666666666667;
         this.isTrap = false;
         this.isOpen = false;
         this.isLocked = true;
         this.trigMC._x = this.pos.x;
         this.trigMC._y = this.pos.y;
         this.trigMC._xscale = this.trigMC._yscale = this.r * 1.5;
         this.trigMC.gotoAndStop("exit_closed");
         this.trigMC._visible = true;
      }
      else if(this.isTrap)
      {
         this.openFrameLabel = "open_Trap";
         this.closedFrameLabel = "closing_Trap";
         this.mc.gotoAndStop("open_Trap");
         this.pos.x = params[0];
         this.pos.y = params[1];
         this.r = tiles.xw * 0.4166666666666667;
         this.isOpen = true;
         this.isLocked = false;
         this.isTrap = true;
         this.trigMC._x = this.pos.x;
         this.trigMC._y = this.pos.y;
         this.trigMC._xscale = this.trigMC._yscale = this.r * 1;
         this.trigMC.gotoAndStop("exit_closed");
         this.trigMC._visible = true;
      }
      else
      {
         this.openFrameLabel = "opening_Trek";
         this.closedFrameLabel = "closing_Trek";
         this.pos.x = this.doorpos.x;
         this.pos.y = this.doorpos.y;
         this.r = tiles.xw * 0.8333333333333334;
         this.isOpen = false;
         this.isLocked = false;
         this.isTrap = false;
         this.mc.gotoAndStop("closed_Trek");
      }
      objects.AddToGrid(this);
      objects.Moved(this);
      this.mc._xscale = this.mc._yscale = 2 * this.doorcell_N.yw;
      this.mc._x = this.doorcell_N.pos.x;
      this.mc._y = this.doorcell_N.pos.y;
      if(this.vert == 1)
      {
         if(this.deltaJ == 0)
         {
            this.mc._rotation = 90;
            this.mc._y -= 1;
         }
         else
         {
            this.mc._y += this.doorcell_N.yw * 2;
            this.mc._rotation = 270;
         }
      }
      else if(this.deltaI == 0)
      {
         this.mc._rotation = 0;
         this.mc._x -= 1;
      }
      else
      {
         this.mc._x += this.doorcell_N.xw * 2;
         this.mc._rotation = 180;
      }
      this.mc._visible = true;
      this.UpdateEdges();
   }
};
TestDoorObject.prototype.UnInit = function()
{
   if(this.vert == 0)
   {
      this.doorcell_N.eR = this.openStateFront;
      this.doorcell_P.eL = this.openStateBack;
   }
   else
   {
      this.doorcell_N.eD = this.openStateFront;
      this.doorcell_P.eU = this.openStateBack;
   }
   objects.RemoveFromGrid(this);
   objects.EndUpdate(this);
};
TestDoorObject.prototype.DumpInitData = function()
{
   var _loc2_ = "" + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y + OBJPARAM_SEPERATION_CHAR + this.vert + OBJPARAM_SEPERATION_CHAR + Number(this.isTrap) + OBJPARAM_SEPERATION_CHAR + (this.doorI - this.deltaI) + OBJPARAM_SEPERATION_CHAR + (this.doorJ - this.deltaJ) + OBJPARAM_SEPERATION_CHAR + Number(this.isLocked) + OBJPARAM_SEPERATION_CHAR + this.deltaI + OBJPARAM_SEPERATION_CHAR + this.deltaJ;
   return _loc2_;
};
TestDoorObject.prototype.UpdateEdges = function()
{
   if(this.vert == 0)
   {
      if(this.isOpen)
      {
         this.doorcell_N.eR = this.openStateFront;
         this.doorcell_P.eL = this.openStateBack;
      }
      else
      {
         this.doorcell_N.eR = EID_SOLID;
         this.doorcell_P.eL = EID_SOLID;
      }
   }
   else if(this.isOpen)
   {
      this.doorcell_N.eD = this.openStateFront;
      this.doorcell_P.eU = this.openStateBack;
   }
   else
   {
      this.doorcell_N.eD = EID_SOLID;
      this.doorcell_P.eU = EID_SOLID;
   }
};
TestDoorObject.prototype.Draw = function()
{
   if(this.isOpen)
   {
      this.mc.gotoAndPlay(this.openFrameLabel);
      this.trigMC.gotoAndStop("exit_open");
   }
   else
   {
      this.mc.gotoAndPlay(this.closedFrameLabel);
      this.trigMC.gotoAndStop("exit_closed");
   }
};
TestDoorObject.prototype.IdleAfterDeath = function()
{
   objects.RemoveFromGrid(this);
};
TestDoorObject.prototype.TestVsPlayer = function(guy)
{
   var _loc5_ = guy.pos;
   var _loc3_ = this.pos.x - guy.pos.x;
   var _loc2_ = this.pos.y - guy.pos.y;
   if(Math.sqrt(_loc3_ * _loc3_ + _loc2_ * _loc2_) < this.r + guy.r)
   {
      this.doortimer = 0;
      if(this.isTrap)
      {
         this.Close();
         objects.RemoveFromGrid(this);
         this.TestVsPlayer = null;
      }
      else if(!this.isOpen)
      {
         this.Open();
      }
   }
};
TestDoorObject.prototype.Open = function()
{
   this.isOpen = true;
   this.UpdateEdges();
   this.Draw();
   if(!this.isTrap && !this.isLocked)
   {
      objects.StartUpdate(this);
   }
};
TestDoorObject.prototype.Close = function()
{
   objects.EndUpdate(this);
   this.isOpen = false;
   this.UpdateEdges();
   this.Draw();
};
TestDoorObject.prototype.Update = function()
{
   this.doortimer = this.doortimer + 1;
   if(this.maxtimer < this.doortimer)
   {
      this.Close();
   }
};
