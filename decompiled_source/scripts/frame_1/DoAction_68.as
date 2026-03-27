OBJTYPE_GOLD = 0;
OBJTYPE_BOUNCEBLOCK = 1;
OBJTYPE_LAUNCHPAD = 2;
OBJTYPE_TURRET = 3;
OBJTYPE_FLOORGUARD = 4;
OBJTYPE_PLAYER = 5;
OBJTYPE_DRONE = 6;
OBJTYPE_ONEWAYPLATFORM = 7;
OBJTYPE_THWOMP = 8;
OBJTYPE_TESTDOOR = 9;
OBJTYPE_HOMINGLAUNCHER = 10;
OBJTYPE_EXIT = 11;
OBJTYPE_MINE = 12;
ObjectManager.prototype.GetObjectStates = function()
{
   var _loc3_ = "";
   var _loc2_ = 0;
   while(_loc2_ < this.objArray.length)
   {
      _loc3_ += this.objArray[_loc2_].OBJ_TYPE;
      _loc3_ += OBJTYPE_SEPERATION_CHAR;
      _loc3_ += this.objArray[_loc2_].DumpInitData();
      _loc3_ += OBJECT_SEPERATION_CHAR;
      _loc2_ = _loc2_ + 1;
   }
   var _loc4_;
   if(0 < _loc3_.length)
   {
      _loc4_ = _loc3_.lastIndexOf(OBJECT_SEPERATION_CHAR);
      _loc3_ = _loc3_.substring(0,_loc4_);
   }
   return _loc3_;
};
ObjectManager.prototype.SpawnGameObject = function(OBJ_TYPE, params)
{
   var _loc2_ = this.BuildObject(OBJ_TYPE);
   _loc2_.OBJ_TYPE = OBJ_TYPE;
   _loc2_.Init(params);
   return _loc2_.UID;
};
ObjectManager.prototype.BuildObject = function(OBJ_TYPE)
{
   var _loc2_;
   if(OBJ_TYPE == OBJTYPE_PLAYER)
   {
      _loc2_ = new PlayerObject();
      return _loc2_;
   }
   if(OBJ_TYPE == OBJTYPE_GOLD)
   {
      _loc2_ = new GoldObject();
      return _loc2_;
   }
   if(OBJ_TYPE == OBJTYPE_BOUNCEBLOCK)
   {
      _loc2_ = new BounceBlockObject();
      return _loc2_;
   }
   if(OBJ_TYPE == OBJTYPE_LAUNCHPAD)
   {
      _loc2_ = new LaunchPadObject();
      return _loc2_;
   }
   if(OBJ_TYPE == OBJTYPE_TURRET)
   {
      _loc2_ = new TurretObject();
      return _loc2_;
   }
   if(OBJ_TYPE == OBJTYPE_FLOORGUARD)
   {
      _loc2_ = new FloorGuardObject();
      return _loc2_;
   }
   if(OBJ_TYPE == OBJTYPE_DRONE)
   {
      _loc2_ = new DroneObject();
      return _loc2_;
   }
   if(OBJ_TYPE == OBJTYPE_ONEWAYPLATFORM)
   {
      _loc2_ = new OneWayPlatformObject();
      return _loc2_;
   }
   if(OBJ_TYPE == OBJTYPE_THWOMP)
   {
      _loc2_ = new ThwompObject();
      return _loc2_;
   }
   if(OBJ_TYPE == OBJTYPE_TESTDOOR)
   {
      _loc2_ = new TestDoorObject();
      return _loc2_;
   }
   if(OBJ_TYPE == OBJTYPE_HOMINGLAUNCHER)
   {
      _loc2_ = new HomingLauncherObject();
      return _loc2_;
   }
   if(OBJ_TYPE == OBJTYPE_EXIT)
   {
      _loc2_ = new ExitObject();
      return _loc2_;
   }
   if(OBJ_TYPE == OBJTYPE_MINE)
   {
      _loc2_ = new MineObject();
      return _loc2_;
   }
};
