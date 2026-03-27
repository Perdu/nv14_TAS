LEVEL_SEPERATION_CHAR = "|";
OBJECT_SEPERATION_CHAR = "!";
OBJTYPE_SEPERATION_CHAR = "^";
OBJPARAM_SEPERATION_CHAR = ",";
NinjaGame.prototype.DumpLevelData = function()
{
   var _loc2_ = this.DumpMapData();
   var _loc4_ = this.DumpObjData();
   var _loc3_ = _loc2_ + LEVEL_SEPERATION_CHAR + _loc4_;
   return _loc3_;
};
NinjaGame.prototype.DumpMapData = function()
{
   var _loc1_ = tiles.GetTileStates();
   return _loc1_;
};
NinjaGame.prototype.DumpObjData = function()
{
   var _loc1_ = objects.GetObjectStates();
   return _loc1_;
};
