TileMapCell.prototype.SetState = function(ID)
{
   if(ID == TID_EMPTY)
   {
      this.Clear();
   }
   else
   {
      this.ID = ID;
      this.UpdateType();
      this.UpdateEdges();
      this.UpdateNeighbors();
   }
};
TileMapCell.prototype.Clear = function()
{
   this.ID = TID_EMPTY;
   this.UpdateType();
   this.UpdateEdges();
   this.UpdateNeighbors();
   this.Draw();
};
TileMapCell.prototype.UpdateNeighbors = function()
{
   if(this.nU != null)
   {
      this.nU.UpdateEdges();
   }
   if(this.nD != null)
   {
      this.nD.UpdateEdges();
   }
   if(this.nL != null)
   {
      this.nL.UpdateEdges();
   }
   if(this.nR != null)
   {
      this.nR.UpdateEdges();
   }
};
TileMapCell.prototype.UpdateType = function()
{
   var _loc2_;
   if(0 < this.ID)
   {
      if(this.ID < CTYPE_45DEG)
      {
         this.CTYPE = CTYPE_FULL;
         this.signx = 0;
         this.signy = 0;
         this.sx = 0;
         this.sy = 0;
      }
      else if(this.ID < CTYPE_CONCAVE)
      {
         this.CTYPE = CTYPE_45DEG;
         if(this.ID == TID_45DEGpn)
         {
            this.signx = 1;
            this.signy = -1;
            this.sx = this.signx / 1.4142135623730951;
            this.sy = this.signy / 1.4142135623730951;
         }
         else if(this.ID == TID_45DEGnn)
         {
            this.signx = -1;
            this.signy = -1;
            this.sx = this.signx / 1.4142135623730951;
            this.sy = this.signy / 1.4142135623730951;
         }
         else if(this.ID == TID_45DEGnp)
         {
            this.signx = -1;
            this.signy = 1;
            this.sx = this.signx / 1.4142135623730951;
            this.sy = this.signy / 1.4142135623730951;
         }
         else
         {
            if(this.ID != TID_45DEGpp)
            {
               return false;
            }
            this.signx = 1;
            this.signy = 1;
            this.sx = this.signx / 1.4142135623730951;
            this.sy = this.signy / 1.4142135623730951;
         }
      }
      else if(this.ID < CTYPE_CONVEX)
      {
         this.CTYPE = CTYPE_CONCAVE;
         if(this.ID == TID_CONCAVEpn)
         {
            this.signx = 1;
            this.signy = -1;
            this.sx = 0;
            this.sy = 0;
         }
         else if(this.ID == TID_CONCAVEnn)
         {
            this.signx = -1;
            this.signy = -1;
            this.sx = 0;
            this.sy = 0;
         }
         else if(this.ID == TID_CONCAVEnp)
         {
            this.signx = -1;
            this.signy = 1;
            this.sx = 0;
            this.sy = 0;
         }
         else
         {
            if(this.ID != TID_CONCAVEpp)
            {
               return false;
            }
            this.signx = 1;
            this.signy = 1;
            this.sx = 0;
            this.sy = 0;
         }
      }
      else if(this.ID < CTYPE_22DEGs)
      {
         this.CTYPE = CTYPE_CONVEX;
         if(this.ID == TID_CONVEXpn)
         {
            this.signx = 1;
            this.signy = -1;
            this.sx = 0;
            this.sy = 0;
         }
         else if(this.ID == TID_CONVEXnn)
         {
            this.signx = -1;
            this.signy = -1;
            this.sx = 0;
            this.sy = 0;
         }
         else if(this.ID == TID_CONVEXnp)
         {
            this.signx = -1;
            this.signy = 1;
            this.sx = 0;
            this.sy = 0;
         }
         else
         {
            if(this.ID != TID_CONVEXpp)
            {
               return false;
            }
            this.signx = 1;
            this.signy = 1;
            this.sx = 0;
            this.sy = 0;
         }
      }
      else if(this.ID < CTYPE_22DEGb)
      {
         this.CTYPE = CTYPE_22DEGs;
         if(this.ID == TID_22DEGpnS)
         {
            this.signx = 1;
            this.signy = -1;
            _loc2_ = 2.23606797749979;
            this.sx = this.signx * 1 / _loc2_;
            this.sy = this.signy * 2 / _loc2_;
         }
         else if(this.ID == TID_22DEGnnS)
         {
            this.signx = -1;
            this.signy = -1;
            _loc2_ = 2.23606797749979;
            this.sx = this.signx * 1 / _loc2_;
            this.sy = this.signy * 2 / _loc2_;
         }
         else if(this.ID == TID_22DEGnpS)
         {
            this.signx = -1;
            this.signy = 1;
            _loc2_ = 2.23606797749979;
            this.sx = this.signx * 1 / _loc2_;
            this.sy = this.signy * 2 / _loc2_;
         }
         else
         {
            if(this.ID != TID_22DEGppS)
            {
               return false;
            }
            this.signx = 1;
            this.signy = 1;
            _loc2_ = 2.23606797749979;
            this.sx = this.signx * 1 / _loc2_;
            this.sy = this.signy * 2 / _loc2_;
         }
      }
      else if(this.ID < CTYPE_67DEGs)
      {
         this.CTYPE = CTYPE_22DEGb;
         if(this.ID == TID_22DEGpnB)
         {
            this.signx = 1;
            this.signy = -1;
            _loc2_ = 2.23606797749979;
            this.sx = this.signx * 1 / _loc2_;
            this.sy = this.signy * 2 / _loc2_;
         }
         else if(this.ID == TID_22DEGnnB)
         {
            this.signx = -1;
            this.signy = -1;
            _loc2_ = 2.23606797749979;
            this.sx = this.signx * 1 / _loc2_;
            this.sy = this.signy * 2 / _loc2_;
         }
         else if(this.ID == TID_22DEGnpB)
         {
            this.signx = -1;
            this.signy = 1;
            _loc2_ = 2.23606797749979;
            this.sx = this.signx * 1 / _loc2_;
            this.sy = this.signy * 2 / _loc2_;
         }
         else
         {
            if(this.ID != TID_22DEGppB)
            {
               return false;
            }
            this.signx = 1;
            this.signy = 1;
            _loc2_ = 2.23606797749979;
            this.sx = this.signx * 1 / _loc2_;
            this.sy = this.signy * 2 / _loc2_;
         }
      }
      else if(this.ID < CTYPE_67DEGb)
      {
         this.CTYPE = CTYPE_67DEGs;
         if(this.ID == TID_67DEGpnS)
         {
            this.signx = 1;
            this.signy = -1;
            _loc2_ = 2.23606797749979;
            this.sx = this.signx * 2 / _loc2_;
            this.sy = this.signy * 1 / _loc2_;
         }
         else if(this.ID == TID_67DEGnnS)
         {
            this.signx = -1;
            this.signy = -1;
            _loc2_ = 2.23606797749979;
            this.sx = this.signx * 2 / _loc2_;
            this.sy = this.signy * 1 / _loc2_;
         }
         else if(this.ID == TID_67DEGnpS)
         {
            this.signx = -1;
            this.signy = 1;
            _loc2_ = 2.23606797749979;
            this.sx = this.signx * 2 / _loc2_;
            this.sy = this.signy * 1 / _loc2_;
         }
         else
         {
            if(this.ID != TID_67DEGppS)
            {
               return false;
            }
            this.signx = 1;
            this.signy = 1;
            _loc2_ = 2.23606797749979;
            this.sx = this.signx * 2 / _loc2_;
            this.sy = this.signy * 1 / _loc2_;
         }
      }
      else if(this.ID < CTYPE_HALF)
      {
         this.CTYPE = CTYPE_67DEGb;
         if(this.ID == TID_67DEGpnB)
         {
            this.signx = 1;
            this.signy = -1;
            _loc2_ = 2.23606797749979;
            this.sx = this.signx * 2 / _loc2_;
            this.sy = this.signy * 1 / _loc2_;
         }
         else if(this.ID == TID_67DEGnnB)
         {
            this.signx = -1;
            this.signy = -1;
            _loc2_ = 2.23606797749979;
            this.sx = this.signx * 2 / _loc2_;
            this.sy = this.signy * 1 / _loc2_;
         }
         else if(this.ID == TID_67DEGnpB)
         {
            this.signx = -1;
            this.signy = 1;
            _loc2_ = 2.23606797749979;
            this.sx = this.signx * 2 / _loc2_;
            this.sy = this.signy * 1 / _loc2_;
         }
         else
         {
            if(this.ID != TID_67DEGppB)
            {
               return false;
            }
            this.signx = 1;
            this.signy = 1;
            _loc2_ = 2.23606797749979;
            this.sx = this.signx * 2 / _loc2_;
            this.sy = this.signy * 1 / _loc2_;
         }
      }
      else
      {
         this.CTYPE = CTYPE_HALF;
         if(this.ID == TID_HALFd)
         {
            this.signx = 0;
            this.signy = -1;
            this.sx = this.signx;
            this.sy = this.signy;
         }
         else if(this.ID == TID_HALFu)
         {
            this.signx = 0;
            this.signy = 1;
            this.sx = this.signx;
            this.sy = this.signy;
         }
         else if(this.ID == TID_HALFl)
         {
            this.signx = 1;
            this.signy = 0;
            this.sx = this.signx;
            this.sy = this.signy;
         }
         else
         {
            if(this.ID != TID_HALFr)
            {
               return false;
            }
            this.signx = -1;
            this.signy = 0;
            this.sx = this.signx;
            this.sy = this.signy;
         }
      }
   }
   else
   {
      this.CTYPE = CTYPE_EMPTY;
      this.signx = 0;
      this.signy = 0;
      this.sx = 0;
      this.sy = 0;
   }
};
