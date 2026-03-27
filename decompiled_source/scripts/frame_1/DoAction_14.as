TileMapCell.prototype.UpdateEdges = function()
{
   var _loc2_ = this.nU;
   if(this.ID == TID_EMPTY)
   {
      if(_loc2_.ID == TID_EMPTY)
      {
         this.eU = EID_OFF;
      }
      else if(_loc2_.ID == TID_FULL)
      {
         this.eU = EID_SOLID;
      }
      else if(_loc2_.signy * -1 <= 0 || _loc2_.ID == TID_67DEGpnS || _loc2_.ID == TID_67DEGnnS)
      {
         this.eU = EID_INTERESTING;
      }
      else
      {
         this.eU = EID_SOLID;
      }
   }
   else if(this.ID == TID_FULL)
   {
      if(_loc2_.ID == TID_FULL)
      {
         this.eU = EID_OFF;
      }
      else if(_loc2_.ID == TID_EMPTY)
      {
         this.eU = EID_OFF;
      }
      else if(_loc2_.signy * -1 <= 0 || _loc2_.ID == TID_67DEGpnS || _loc2_.ID == TID_67DEGnnS)
      {
         this.eU = EID_INTERESTING;
      }
      else
      {
         this.eU = EID_OFF;
      }
   }
   else if(0 <= this.signy * -1)
   {
      if(_loc2_.ID == TID_EMPTY)
      {
         this.eU = EID_OFF;
      }
      else if(_loc2_.ID == TID_FULL)
      {
         this.eU = EID_SOLID;
      }
      else if(_loc2_.signy * -1 <= 0 || _loc2_.ID == TID_67DEGpnS || _loc2_.ID == TID_67DEGnnS)
      {
         this.eU = EID_INTERESTING;
      }
      else
      {
         this.eU = EID_SOLID;
      }
   }
   else if(this.ID == TID_67DEGppS || this.ID == TID_67DEGnpS)
   {
      if(_loc2_.ID == TID_EMPTY)
      {
         this.eU = EID_OFF;
      }
      else if(_loc2_.ID == TID_FULL)
      {
         this.eU = EID_SOLID;
      }
      else if(_loc2_.signy * -1 <= 0 || _loc2_.ID == TID_67DEGpnS || _loc2_.ID == TID_67DEGnnS)
      {
         this.eU = EID_INTERESTING;
      }
      else if(0 < _loc2_.signy * -1 || _loc2_.ID == TID_FULL)
      {
         this.eU = EID_SOLID;
      }
      else
      {
         this.eU = EID_OFF;
      }
   }
   else if(_loc2_.ID == TID_FULL)
   {
      this.eU = EID_OFF;
   }
   else if(_loc2_.ID == TID_EMPTY)
   {
      this.eU = EID_OFF;
   }
   else if(_loc2_.signy * -1 <= 0 || _loc2_.ID == TID_67DEGpnS || _loc2_.ID == TID_67DEGnnS)
   {
      this.eU = EID_INTERESTING;
   }
   else
   {
      this.eU = EID_OFF;
   }
   _loc2_ = this.nD;
   if(this.ID == TID_EMPTY)
   {
      if(_loc2_.ID == TID_EMPTY)
      {
         this.eD = EID_OFF;
      }
      else if(_loc2_.ID == TID_FULL)
      {
         this.eD = EID_SOLID;
      }
      else if(_loc2_.signy * 1 <= 0 || _loc2_.ID == TID_67DEGppS || _loc2_.ID == TID_67DEGnpS)
      {
         this.eD = EID_INTERESTING;
      }
      else
      {
         this.eD = EID_SOLID;
      }
   }
   else if(this.ID == TID_FULL)
   {
      if(_loc2_.ID == TID_FULL)
      {
         this.eD = EID_OFF;
      }
      else if(_loc2_.ID == TID_EMPTY)
      {
         this.eD = EID_OFF;
      }
      else if(_loc2_.signy * 1 <= 0 || _loc2_.ID == TID_67DEGppS || _loc2_.ID == TID_67DEGnpS)
      {
         this.eD = EID_INTERESTING;
      }
      else
      {
         this.eD = EID_OFF;
      }
   }
   else if(0 <= this.signy * 1)
   {
      if(_loc2_.ID == TID_EMPTY)
      {
         this.eD = EID_OFF;
      }
      else if(_loc2_.ID == TID_FULL)
      {
         this.eD = EID_SOLID;
      }
      else if(_loc2_.signy * 1 <= 0 || _loc2_.ID == TID_67DEGppS || _loc2_.ID == TID_67DEGnpS)
      {
         this.eD = EID_INTERESTING;
      }
      else
      {
         this.eD = EID_SOLID;
      }
   }
   else if(this.ID == TID_67DEGpnS || this.ID == TID_67DEGnnS)
   {
      if(_loc2_.ID == TID_EMPTY)
      {
         this.eD = EID_OFF;
      }
      else if(_loc2_.ID == TID_FULL)
      {
         this.eD = EID_SOLID;
      }
      else if(_loc2_.signy * 1 <= 0 || _loc2_.ID == TID_67DEGppS || _loc2_.ID == TID_67DEGnpS)
      {
         this.eD = EID_INTERESTING;
      }
      else if(0 < _loc2_.signy * 1 || _loc2_.ID == TID_FULL)
      {
         this.eD = EID_SOLID;
      }
      else
      {
         this.eD = EID_OFF;
      }
   }
   else if(_loc2_.ID == TID_FULL)
   {
      this.eD = EID_OFF;
   }
   else if(_loc2_.ID == TID_EMPTY)
   {
      this.eD = EID_OFF;
   }
   else if(_loc2_.signy * 1 <= 0 || _loc2_.ID == TID_67DEGppS || _loc2_.ID == TID_67DEGnpS)
   {
      this.eD = EID_INTERESTING;
   }
   else
   {
      this.eD = EID_OFF;
   }
   _loc2_ = this.nR;
   if(this.ID == TID_EMPTY)
   {
      if(_loc2_.ID == TID_EMPTY)
      {
         this.eR = EID_OFF;
      }
      else if(_loc2_.ID == TID_FULL)
      {
         this.eR = EID_SOLID;
      }
      else if(_loc2_.signx * 1 <= 0 || _loc2_.ID == TID_22DEGpnS || _loc2_.ID == TID_22DEGppS)
      {
         this.eR = EID_INTERESTING;
      }
      else
      {
         this.eR = EID_SOLID;
      }
   }
   else if(this.ID == TID_FULL)
   {
      if(_loc2_.ID == TID_FULL)
      {
         this.eR = EID_OFF;
      }
      else if(_loc2_.ID == TID_EMPTY)
      {
         this.eR = EID_OFF;
      }
      else if(_loc2_.signx * 1 <= 0 || _loc2_.ID == TID_22DEGpnS || _loc2_.ID == TID_22DEGppS)
      {
         this.eR = EID_INTERESTING;
      }
      else
      {
         this.eR = EID_OFF;
      }
   }
   else if(0 <= this.signx * 1)
   {
      if(_loc2_.ID == TID_EMPTY)
      {
         this.eR = EID_OFF;
      }
      else if(_loc2_.ID == TID_FULL)
      {
         this.eR = EID_SOLID;
      }
      else if(_loc2_.signx * 1 <= 0 || _loc2_.ID == TID_22DEGpnS || _loc2_.ID == TID_22DEGppS)
      {
         this.eR = EID_INTERESTING;
      }
      else
      {
         this.eR = EID_SOLID;
      }
   }
   else if(this.ID == TID_22DEGnnS || this.ID == TID_22DEGnpS)
   {
      if(_loc2_.ID == TID_EMPTY)
      {
         this.eR = EID_OFF;
      }
      else if(_loc2_.ID == TID_FULL)
      {
         this.eR = EID_SOLID;
      }
      else if(_loc2_.signx * 1 <= 0 || _loc2_.ID == TID_22DEGpnS || _loc2_.ID == TID_22DEGppS)
      {
         this.eR = EID_INTERESTING;
      }
      else if(_loc2_.ID == TID_FULL || 0 < _loc2_.signx * 1)
      {
         this.eR = EID_SOLID;
      }
      else
      {
         this.eR = EID_OFF;
      }
   }
   else if(_loc2_.ID == TID_FULL)
   {
      this.eR = EID_OFF;
   }
   else if(_loc2_.ID == TID_EMPTY)
   {
      this.eR = EID_OFF;
   }
   else if(_loc2_.signx * 1 <= 0 || _loc2_.ID == TID_22DEGpnS || _loc2_.ID == TID_22DEGppS)
   {
      this.eR = EID_INTERESTING;
   }
   else
   {
      this.eR = EID_OFF;
   }
   _loc2_ = this.nL;
   if(this.ID == TID_EMPTY)
   {
      if(_loc2_.ID == TID_EMPTY)
      {
         this.eL = EID_OFF;
      }
      else if(_loc2_.ID == TID_FULL)
      {
         this.eL = EID_SOLID;
      }
      else if(_loc2_.signx * -1 <= 0 || _loc2_.ID == TID_22DEGnnS || _loc2_.ID == TID_22DEGnpS)
      {
         this.eL = EID_INTERESTING;
      }
      else
      {
         this.eL = EID_SOLID;
      }
   }
   else if(this.ID == TID_FULL)
   {
      if(_loc2_.ID == TID_FULL)
      {
         this.eL = EID_OFF;
      }
      else if(_loc2_.ID == TID_EMPTY)
      {
         this.eL = EID_OFF;
      }
      else if(_loc2_.signx * -1 <= 0 || _loc2_.ID == TID_22DEGnnS || _loc2_.ID == TID_22DEGnpS)
      {
         this.eL = EID_INTERESTING;
      }
      else
      {
         this.eL = EID_OFF;
      }
   }
   else if(0 <= this.signx * -1)
   {
      if(_loc2_.ID == TID_EMPTY)
      {
         this.eL = EID_OFF;
      }
      else if(_loc2_.ID == TID_FULL)
      {
         this.eL = EID_SOLID;
      }
      else if(_loc2_.signx * -1 <= 0 || _loc2_.ID == TID_22DEGnnS || _loc2_.ID == TID_22DEGnpS)
      {
         this.eL = EID_INTERESTING;
      }
      else
      {
         this.eL = EID_SOLID;
      }
   }
   else if(this.ID == TID_22DEGpnS || this.ID == TID_22DEGppS)
   {
      if(_loc2_.ID == TID_EMPTY)
      {
         this.eL = EID_OFF;
      }
      else if(_loc2_.ID == TID_FULL)
      {
         this.eL = EID_SOLID;
      }
      else if(_loc2_.signx * -1 <= 0 || _loc2_.ID == TID_22DEGnnS || _loc2_.ID == TID_22DEGnpS)
      {
         this.eL = EID_INTERESTING;
      }
      else if(0 < _loc2_.signx * -1 || _loc2_.ID == TID_FULL)
      {
         this.eL = EID_SOLID;
      }
      else
      {
         this.eL = EID_OFF;
      }
   }
   else if(_loc2_.ID == TID_FULL)
   {
      this.eL = EID_OFF;
   }
   else if(_loc2_.ID == TID_EMPTY)
   {
      this.eL = EID_OFF;
   }
   else if(_loc2_.signx * -1 <= 0 || _loc2_.ID == TID_22DEGnnS || _loc2_.ID == TID_22DEGnpS)
   {
      this.eL = EID_INTERESTING;
   }
   else
   {
      this.eL = EID_OFF;
   }
   this.Draw();
};
