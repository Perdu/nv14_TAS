function NinjaGraphicsSystem()
{
   this.rootbuffer = _root.createEmptyMovieClip("rootbuffer",1000);
   this.front_depth = 1000;
   this.back_depth = 1000;
   this.stepsize = 100;
   this.bufferList = new Object();
   this.bufferList[LAYER_BACKGROUND] = this.CreateSpriteBuffer(this.GetNextDepth_Front());
   this.bufferList[LAYER_WALLS] = this.CreateSpriteBuffer(this.GetNextDepth_Front());
   this.bufferList[LAYER_PARTICLES_BACK] = this.CreateSpriteBuffer(this.GetNextDepth_Front());
   this.bufferList[LAYER_OBJECTS] = this.CreateSpriteBuffer(this.GetNextDepth_Front());
   this.bufferList[LAYER_PLAYER] = this.CreateSpriteBuffer(this.GetNextDepth_Front());
   this.bufferList[LAYER_PARTICLES_FRONT] = this.CreateSpriteBuffer(this.GetNextDepth_Front());
   this.bufferList[LAYER_TILES] = this.CreateSpriteBuffer(this.GetNextDepth_Front());
   this.bufferList[LAYER_TILES2] = this.CreateSpriteBuffer(this.GetNextDepth_Front());
   this.bufferList[LAYER_EDITOR] = this.CreateSpriteBuffer(this.GetNextDepth_Front());
   this.bufferList[LAYER_EDITORGUI] = this.CreateSpriteBuffer(this.GetNextDepth_Front());
   this.bufferList[LAYER_CONSOLE] = this.CreateSpriteBuffer(this.GetNextDepth_Front());
   this.bufferList[LAYER_GUI] = this.CreateSpriteBuffer(this.GetNextDepth_Front());
   this.depthList = new Object();
   this.depthList[LAYER_BACKGROUND] = 0;
   this.depthList[LAYER_TILES] = 0;
   this.depthList[LAYER_TILES2] = 0;
   this.depthList[LAYER_WALLS] = 0;
   this.depthList[LAYER_OBJECTS] = 0;
   this.depthList[LAYER_PLAYER] = 0;
   this.depthList[LAYER_PARTICLES_FRONT] = 0;
   this.depthList[LAYER_PARTICLES_BACK] = 0;
   this.depthList[LAYER_EDITOR] = 0;
   this.depthList[LAYER_EDITORGUI] = 0;
   this.depthList[LAYER_CONSOLE] = 0;
   this.depthList[LAYER_GUI] = 0;
   this.reservedList = new Object();
}
LAYER_BACKGROUND = 0;
LAYER_TILES = 1;
LAYER_WALLS = 2;
LAYER_OBJECTS = 3;
LAYER_PLAYER = 4;
LAYER_PARTICLES_FRONT = 5;
LAYER_EDITOR = 6;
LAYER_EDITORGUI = 7;
LAYER_CONSOLE = 8;
LAYER_GUI = 9;
LAYER_TILES2 = 10;
LAYER_PARTICLES_BACK = 11;
NinjaGraphicsSystem.prototype.CreateSpriteBuffer = function(depth)
{
   var _loc2_ = this.rootbuffer.createEmptyMovieClip("spritebuffer" + depth,depth);
   _loc2_._x = 0;
   _loc2_._y = 0;
   return _loc2_;
};
NinjaGraphicsSystem.prototype.CreateSprite = function(linkage, layerID)
{
   var _loc4_ = this.bufferList[layerID];
   if(_loc4_ == null)
   {
      return null;
   }
   var _loc2_ = this.depthList[layerID];
   var _loc5_ = _loc4_.attachMovie(linkage,linkage + _loc2_,_loc2_);
   this.depthList[layerID] += 1;
   return _loc5_;
};
NinjaGraphicsSystem.prototype.CreateEmptySprite = function(layerID)
{
   var _loc4_ = this.bufferList[layerID];
   if(_loc4_ == null)
   {
      return null;
   }
   var _loc2_ = this.depthList[layerID];
   var _loc5_ = _loc4_.createEmptyMovieClip("emptyMC" + _loc2_,_loc2_);
   this.depthList[layerID] += 1;
   return _loc5_;
};
NinjaGraphicsSystem.prototype.DestroyMC = function(mc)
{
   mc.swapDepths(1048000);
   mc.removeMovieClip();
};
NinjaGraphicsSystem.prototype.CreateBuffer = function(mcDepth)
{
   var _loc4_;
   var _loc3_;
   if(this.reservedList[mcDepth] == null)
   {
      this.reservedList[mcDepth] = mcDepth;
      _loc4_ = "buffer" + mcDepth;
      _loc3_ = this.rootbuffer.createEmptyMovieClip(_loc4_,mcDepth);
      _loc3_._x = Stage.width / 2;
      _loc3_._y = Stage.height / 2;
      return _loc3_;
   }
};
NinjaGraphicsSystem.prototype.GetLayerDepth = function(layerID)
{
   var _loc2_ = this.depthList[layerID];
   if(_loc2_ != null)
   {
      return _loc2_;
   }
};
NinjaGraphicsSystem.prototype.GetNextDepth_Front = function()
{
   this.front_depth += this.stepsize;
   return this.front_depth;
};
NinjaGraphicsSystem.prototype.GetNextDepth_Back = function()
{
   this.back_depth -= this.stepsize;
   return this.back_depth;
};
