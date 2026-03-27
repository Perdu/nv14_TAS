function Vector2(x, y)
{
   this.x = x;
   this.y = y;
}
Vector2.prototype.ToString = function()
{
   return "(" + this.x + "," + this.y + ")";
};
Vector2.prototype.clone = function()
{
   var _loc2_ = new Vector2(this.x,this.y);
   return _loc2_;
};
Vector2.prototype.plus = function(v2)
{
   var _loc2_ = new Vector2(this.x + v2.x,this.y + v2.y);
   return _loc2_;
};
Vector2.prototype.minus = function(v2)
{
   var _loc2_ = new Vector2(this.x - v2.x,this.y - v2.y);
   return _loc2_;
};
Vector2.prototype.normR = function()
{
   var _loc2_ = new Vector2(this.y * -1,this.x);
   return _loc2_;
};
Vector2.prototype.dir = function()
{
   var _loc2_ = this.clone();
   _loc2_.normalize();
   return _loc2_;
};
Vector2.prototype.proj = function(v2)
{
   var _loc3_ = v2.dot(v2);
   var _loc2_;
   if(_loc3_ == 0)
   {
      _loc2_ = this.clone();
   }
   else
   {
      _loc2_ = v2.clone();
      _loc2_.mult(this.dot(v2) / _loc3_);
   }
   return _loc2_;
};
Vector2.prototype.projLen = function(v2)
{
   var _loc2_ = v2.dot(v2);
   if(_loc2_ == 0)
   {
      return 0;
   }
   return Math.abs(this.dot(v2) / _loc2_);
};
Vector2.prototype.dot = function(v2)
{
   return this.x * v2.x + this.y * v2.y;
};
Vector2.prototype.cross = function(v2)
{
   return this.x * v2.y - this.y * v2.x;
};
Vector2.prototype.len = function()
{
   return Math.sqrt(this.x * this.x + this.y * this.y);
};
Vector2.prototype.copy = function(v2)
{
   this.x = v2.x;
   this.y = v2.y;
};
Vector2.prototype.mult = function(s)
{
   this.x *= s;
   this.y *= s;
};
Vector2.prototype.normalize = function()
{
   var _loc2_ = this.len();
   if(_loc2_ != 0)
   {
      this.x /= _loc2_;
      this.y /= _loc2_;
   }
};
Vector2.prototype.pluseq = function(v2)
{
   this.x += v2.x;
   this.y += v2.y;
};
Vector2.prototype.minuseq = function(v2)
{
   this.x -= v2.x;
   this.y -= v2.y;
};
