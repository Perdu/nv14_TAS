function ObjectManager()
{
   this.InitDataStructs();
}
ObjectManager.prototype.InitDataStructs = function()
{
   this.objList = new Object();
   this.objArray = new Array();
   this.numObjs = 0;
   this.nextID = 0;
   this.gridList = new Object();
   this.gridNum = 0;
   this.updateList = new Object();
   this.updateNum = 0;
   this.drawList = new Object();
   this.drawNum = 0;
   this.thinkList = new Object();
   this.thinkNum = 0;
   this.curThinker = null;
   this.thinkRate = 2;
   this.thinkTimer = 0;
};
ObjectManager.prototype.Register = function(obj)
{
   obj.UID = this.nextID++;
   this.objList[obj.UID] = obj;
   this.objArray.push(obj);
   this.numObjs = this.numObjs + 1;
};
ObjectManager.prototype.AddToGrid = function(obj)
{
   obj.cell = tiles.GetTile_V(obj.pos);
   obj.cell.InsertObj(obj);
   this.gridList[obj.UID] = obj;
   this.gridNum = this.gridNum + 1;
};
ObjectManager.prototype.RemoveFromGrid = function(obj)
{
   if(this.gridList[obj.UID] != null)
   {
      obj.cell.RemoveObj(obj);
      delete this.gridList[obj.UID];
      this.gridNum = this.gridNum - 1;
   }
};
ObjectManager.prototype.Moved = function(obj)
{
   var _loc2_ = obj.cell;
   n = tiles.GetTile_V(obj.pos);
   if(_loc2_ != n)
   {
      _loc2_.RemoveObj(obj);
      obj.cell = n;
      n.InsertObj(obj);
      return true;
   }
   return false;
};
ObjectManager.prototype.GetObj = function(ID)
{
   var _loc3_ = this.objList[ID];
   if(_loc3_ != null)
   {
      return this.objList[ID];
   }
};
ObjectManager.prototype.GetObjType = function(obj)
{
   return obj.OBJ_TYPE;
};
ObjectManager.prototype.IdleObjectsAfterDeath = function()
{
   for(var _loc2_ in this.objList)
   {
      this.objList[_loc2_].IdleAfterDeath();
   }
};
ObjectManager.prototype.DumpThinkList = function()
{
   var _loc4_ = "THINK LIST:\n";
   var _loc6_ = this.curThinker;
   var _loc5_ = _loc6_.UID;
   _loc4_ += "head: " + _loc5_;
   _loc4_ += "\n" + _loc6_.prevThinker.UID + "<-" + _loc5_ + "->" + _loc6_.nextThinker.UID;
   if(this.thinkNum == 0)
   {
      _loc4_ += "no thinkers!";
      return _loc4_;
   }
   var _loc3_ = "   ";
   var _loc2_ = _loc6_.nextThinker;
   while(_loc2_.UID != _loc5_)
   {
      _loc4_ += "\n" + _loc3_ + _loc2_.prevThinker.UID + "<-" + _loc2_.UID + "->" + _loc2_.nextThinker.UID;
      _loc2_ = _loc2_.nextThinker;
      _loc3_ += "   ";
   }
   return _loc4_;
};
ObjectManager.prototype.Tick = function()
{
   if(0 < this.updateNum)
   {
      for(var _loc2_ in this.updateList)
      {
         this.updateList[_loc2_].Update();
      }
   }
   if(0 < this.thinkNum)
   {
      if(this.thinkRate < this.thinkTimer)
      {
         this.thinkTimer = 0;
         this.curThinker.Think();
         this.curThinker = this.curThinker.nextThinker;
      }
      else
      {
         this.thinkTimer = this.thinkTimer + 1;
      }
   }
};
ObjectManager.prototype.StartUpdate = function(obj)
{
   if(this.updateList[obj.UID] == null)
   {
      this.updateList[obj.UID] = obj;
      this.updateNum = this.updateNum + 1;
   }
};
ObjectManager.prototype.EndUpdate = function(obj)
{
   if(this.updateList[obj.UID] == null)
   {
      return undefined;
   }
   delete this.updateList[obj.UID];
   this.updateNum = this.updateNum - 1;
};
ObjectManager.prototype.StartDraw = function(obj)
{
   if(this.drawList[obj.UID] == null)
   {
      this.drawList[obj.UID] = obj;
      this.drawNum = this.drawNum + 1;
   }
};
ObjectManager.prototype.EndDraw = function(obj)
{
   if(this.drawList[obj.UID] == null)
   {
      return undefined;
   }
   delete this.drawList[obj.UID];
   this.drawNum = this.drawNum - 1;
};
ObjectManager.prototype.StartThink = function(obj)
{
   if(this.thinkList[obj.UID] == null)
   {
      this.thinkList[obj.UID] = obj;
      this.thinkNum = this.thinkNum + 1;
      if(this.thinkNum == 1)
      {
         this.curThinker = obj;
         obj.nextThinker = obj;
         obj.prevThinker = obj;
      }
      else
      {
         obj.nextThinker = this.curThinker;
         obj.prevThinker = this.curThinker.prevThinker;
         obj.prevThinker.nextThinker = obj;
         obj.nextThinker.prevThinker = obj;
         this.curThinker = obj;
      }
   }
};
ObjectManager.prototype.EndThink = function(obj)
{
   if(this.thinkList[obj.UID] == null)
   {
      return undefined;
   }
   delete this.thinkList[obj.UID];
   this.thinkNum = this.thinkNum - 1;
   if(this.thinkNum <= 0)
   {
      obj.nextThinker = null;
      obj.prevThinker = null;
      this.curThinker = null;
      this.thinkNum = 0;
   }
   else
   {
      obj.nextThinker.prevThinker = obj.prevThinker;
      obj.prevThinker.nextThinker = obj.nextThinker;
      if(obj == this.curThinker)
      {
         this.curThinker = obj.nextThinker;
      }
      obj.nextThinker = null;
      obj.prevThinker = null;
   }
};
ObjectManager.prototype.Clear = function()
{
   for(var _loc2_ in this.thinkList)
   {
      this.EndThink(this.thinkList[_loc2_]);
   }
   for(_loc2_ in this.gridList)
   {
      this.RemoveFromGrid(this.gridList[_loc2_]);
   }
   for(_loc2_ in this.updateList)
   {
      this.EndUpdate(this.updateList[_loc2_]);
   }
   for(_loc2_ in this.drawList)
   {
      this.EndDraw(this.drawList[_loc2_]);
   }
   for(_loc2_ in this.objArray)
   {
      delete this.objArray[_loc2_];
   }
   for(_loc2_ in this.objList)
   {
      this.objList[_loc2_].next = null;
      this.objList[_loc2_].prev = null;
      this.objList[_loc2_].nextThinker = null;
      this.objList[_loc2_].prevThinker = null;
      this.objList[_loc2_].UnInit();
      this.objList[_loc2_].Destruct();
      delete this.objList[_loc2_];
   }
   tiles.ClearGrid();
   delete this.objList;
   delete this.objArray;
   delete this.updateList;
   delete this.drawList;
   delete this.gridList;
   delete this.thinkList;
   delete this.curThinker;
   this.InitDataStructs();
};
ObjectManager.prototype.Draw = function()
{
   for(var _loc2_ in this.drawList)
   {
      this.drawList[_loc2_].Draw();
   }
};
