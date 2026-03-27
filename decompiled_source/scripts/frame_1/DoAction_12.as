function TileMapCell(i, j, x, y, xw, yw)
{
   this.ID = TID_EMPTY;
   this.CTYPE = CTYPE_EMPTY;
   this.i = i;
   this.j = j;
   this.nU = null;
   this.nD = null;
   this.nL = null;
   this.nR = null;
   this.eU = EID_OFF;
   this.eD = EID_OFF;
   this.eL = EID_OFF;
   this.eR = EID_OFF;
   this.gx = 0;
   this.gy = GRAV;
   this.d = DRAG;
   this.next = null;
   this.prev = null;
   this.objcounter = 0;
   this.pos = new Vector2(x,y);
   this.xw = xw;
   this.yw = yw;
   this.minx = this.pos.x - this.xw;
   this.maxx = this.pos.x + this.xw;
   this.miny = this.pos.y - this.yw;
   this.maxy = this.pos.y + this.yw;
   this.signx = 0;
   this.signy = 0;
   this.sx = 0;
   this.sy = 0;
   var _loc2_ = false;
   var _loc3_;
   if(!_loc2_)
   {
      this.mc = gfx.CreateSprite("tileMC",LAYER_TILES);
      this.mc.gotoAndStop(1);
      this.mc._xscale = this.xw * 2;
      this.mc._yscale = this.yw * 2;
      this.mc._x = this.pos.x;
      this.mc._y = this.pos.y;
      _loc3_ = new Color(this.mc);
      _loc3_.setRGB(7960968);
   }
   else
   {
      this.mc = gfx.CreateSprite("tileMC2",LAYER_TILES2);
      this.mc.gotoAndStop(1);
      this.mc._xscale = this.xw * 2;
      this.mc._yscale = this.yw * 2;
      this.mc._x = this.pos.x;
      this.mc._y = this.pos.y;
   }
}
TID_EMPTY = 0;
TID_FULL = 1;
TID_45DEGpn = 2;
TID_45DEGnn = 3;
TID_45DEGnp = 4;
TID_45DEGpp = 5;
TID_CONCAVEpn = 6;
TID_CONCAVEnn = 7;
TID_CONCAVEnp = 8;
TID_CONCAVEpp = 9;
TID_CONVEXpn = 10;
TID_CONVEXnn = 11;
TID_CONVEXnp = 12;
TID_CONVEXpp = 13;
TID_22DEGpnS = 14;
TID_22DEGnnS = 15;
TID_22DEGnpS = 16;
TID_22DEGppS = 17;
TID_22DEGpnB = 18;
TID_22DEGnnB = 19;
TID_22DEGnpB = 20;
TID_22DEGppB = 21;
TID_67DEGpnS = 22;
TID_67DEGnnS = 23;
TID_67DEGnpS = 24;
TID_67DEGppS = 25;
TID_67DEGpnB = 26;
TID_67DEGnnB = 27;
TID_67DEGnpB = 28;
TID_67DEGppB = 29;
TID_HALFd = 30;
TID_HALFr = 31;
TID_HALFu = 32;
TID_HALFl = 33;
CTYPE_EMPTY = 0;
CTYPE_FULL = 1;
CTYPE_45DEG = 2;
CTYPE_CONCAVE = 6;
CTYPE_CONVEX = 10;
CTYPE_22DEGs = 14;
CTYPE_22DEGb = 18;
CTYPE_67DEGs = 22;
CTYPE_67DEGb = 26;
CTYPE_HALF = 30;
EID_OFF = 0;
EID_INTERESTING = 1;
EID_SOLID = 2;
TileMapCell.prototype.LinkU = function(t)
{
   this.nU = t;
};
TileMapCell.prototype.LinkD = function(t)
{
   this.nD = t;
};
TileMapCell.prototype.LinkL = function(t)
{
   this.nL = t;
};
TileMapCell.prototype.LinkR = function(t)
{
   this.nR = t;
};
TileMapCell.prototype.ToString = function()
{
   var _loc2_ = "(" + this.i + "," + this.j + ")";
   return _loc2_;
};
TileMapCell.prototype.Draw = function()
{
   this.mc.gotoAndStop(this.ID + 1);
};
