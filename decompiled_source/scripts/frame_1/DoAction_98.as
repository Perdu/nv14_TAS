NinjaGame.prototype.InitLoadLevel = function(str)
{
   this.levStr = str;
   var _loc2_ = this.levStr.split(LEVEL_SEPERATION_CHAR);
   this.InitLoadMap(_loc2_[0]);
   this.InitLoadObjects(_loc2_[1]);
};
NinjaGame.prototype.InitLoadMap = function(str)
{
   this.mapStr = str;
   this.CUR_CHAR = 0;
   this.NUM_ROWS = tiles.cols;
   this.NUM_COLS = tiles.rows;
   this.CUR_COL = 0;
   this.CUR_ROW = 0;
   this.MAP_LOADED = false;
};
NinjaGame.prototype.LoadingMap = function()
{
   if(this.NUM_ROWS <= this.CUR_ROW)
   {
      this.CUR_COL = this.CUR_COL + 1;
      this.CUR_ROW = 0;
   }
   if(this.NUM_COLS <= this.CUR_COL)
   {
      return false;
   }
   tiles.SetTileState(this.CUR_COL,this.CUR_ROW,this.mapStr.charCodeAt(this.CUR_CHAR));
   this.CUR_CHAR = this.CUR_CHAR + 1;
   this.CUR_ROW = this.CUR_ROW + 1;
   return true;
};
NinjaGame.prototype.InitLoadObjects = function(str)
{
   objects.Clear();
   this.objStr = str;
   var _loc2_;
   if(0 < this.objStr.length)
   {
      this.oStrArray = this.objStr.split(OBJECT_SEPERATION_CHAR);
      _loc2_ = 0;
      while(_loc2_ < this.oStrArray.length)
      {
         _loc2_ = _loc2_ + 1;
      }
      this.CURRENT_OBJ_LOADING = 0;
      this.objParamList = new Array();
      this.objUIDList = new Array();
   }
   else
   {
      this.CUR_OBJ_LOADING = 0;
      this.oStrArray = new Array();
      this.objParamList = new Array();
      this.objUIDList = new Array();
   }
};
NinjaGame.prototype.InitReloadObjects = function()
{
   this.InitLoadObjects(this.objStr);
};
NinjaGame.prototype.LoadingObjects = function()
{
   var _loc4_;
   var _loc2_;
   if(this.CURRENT_OBJ_LOADING < this.oStrArray.length)
   {
      _loc4_ = this.oStrArray[this.CURRENT_OBJ_LOADING].split(OBJTYPE_SEPERATION_CHAR);
      _loc2_ = _loc4_[1].split(OBJPARAM_SEPERATION_CHAR);
      for(var _loc3_ in _loc2_)
      {
         _loc2_[_loc3_] = Number(_loc2_[_loc3_]);
      }
      this.objUIDList.push(objects.SpawnGameObject(Number(_loc4_[0]),_loc2_));
      this.objParamList.push(_loc2_);
      this.CURRENT_OBJ_LOADING = this.CURRENT_OBJ_LOADING + 1;
      return true;
   }
   return false;
};
