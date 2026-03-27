TileMapCell.prototype.InsertObj = function(obj)
{
   obj.next = this.next;
   obj.prev = this;
   this.prev = null;
   if(this.next != null)
   {
      this.next.prev = obj;
   }
   this.next = obj;
   this.objcounter = this.objcounter + 1;
};
TileMapCell.prototype.RemoveObj = function(obj)
{
   obj.prev.next = obj.next;
   if(obj.next != null)
   {
      obj.next.prev = obj.prev;
   }
   obj.next = null;
   obj.prev = null;
   this.objcounter = this.objcounter - 1;
};
