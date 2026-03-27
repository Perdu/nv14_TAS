function VectorRenderer()
{
   this.buffer = gfx.CreateSpriteBuffer(gfx.GetNextDepth_Front());
   this.buffer._x = 0;
   this.buffer._y = 0;
   this.thickness = 0;
   this.rgb = 0;
   this.alpha = 100;
}
VectorRenderer.prototype.Kill = function()
{
   gfx.DestroyMC(this.buffer);
   delete this.buffer;
};
VectorRenderer.prototype.Hide = function()
{
   this.buffer._visible = false;
};
VectorRenderer.prototype.Show = function()
{
   this.buffer._visible = true;
};
VectorRenderer.prototype.Clear = function()
{
   this.buffer.clear();
   this.buffer.lineStyle(this.thickness,this.rgb,this.alpha);
};
VectorRenderer.prototype.SetStyle = function(thick, rgb, alpha)
{
   this.buffer.lineStyle(thick,rgb,alpha);
};
VectorRenderer.prototype.StartFill = function(x, y, rgb, alpha)
{
   this.buffer.moveTo(x,y);
   this.buffer.beginFill(rgb,alpha);
};
VectorRenderer.prototype.StopFill = function()
{
   this.buffer.endFill();
};
VectorRenderer.prototype.DrawLine = function(va, vb)
{
   this.buffer.moveTo(va.x,va.y);
   this.buffer.lineTo(vb.x,vb.y);
};
VectorRenderer.prototype.DrawLine_S = function(x0, y0, x1, y1)
{
   this.buffer.moveTo(x0,y0);
   this.buffer.lineTo(x1,y1);
};
VectorRenderer.prototype.DrawLinestrip = function(vList)
{
   this.buffer.moveTo(vList[0].x,vList[0].y);
   var _loc2_ = 0;
   while(_loc2_ < vList.length)
   {
      this.buffer.lineTo(vList[_loc2_].x,vList[_loc2_].y);
      _loc2_ = _loc2_ + 1;
   }
};
VectorRenderer.prototype.DrawTri = function(va, vb, vc)
{
   this.buffer.moveTo(va.x,va.y);
   this.buffer.lineTo(vb.x,vb.y);
   this.buffer.lineTo(vc.x,vc.y);
   this.buffer.lineTo(va.x,va.y);
};
VectorRenderer.prototype.DrawTri_S = function(vax, vay, vbx, vby, vcx, vcy)
{
   this.buffer.moveTo(vax,vay);
   this.buffer.lineTo(vbx,vby);
   this.buffer.lineTo(vcx,vcy);
   this.buffer.lineTo(vax,vay);
};
VectorRenderer.prototype.DrawQuad = function(a, b, c, d)
{
   this.buffer.moveTo(a.x,a.y);
   this.buffer.lineTo(b.x,b.y);
   this.buffer.lineTo(c.x,c.y);
   this.buffer.lineTo(d.x,d.y);
   this.buffer.lineTo(a.x,a.y);
};
VectorRenderer.prototype.DrawQuad_S = function(ax, ay, bx, by, cx, cy, dx, dy)
{
   this.buffer.moveTo(ax,ay);
   this.buffer.lineTo(bx,by);
   this.buffer.lineTo(cx,cy);
   this.buffer.lineTo(dx,dy);
   this.buffer.lineTo(ax,ay);
};
VectorRenderer.prototype.DrawPlus = function(v)
{
   this.buffer.moveTo(v.x - 1,v.y);
   this.buffer.lineTo(v.x + 1,v.y);
   this.buffer.moveTo(v.x,v.y - 1);
   this.buffer.lineTo(v.x,v.y + 1);
};
VectorRenderer.prototype.DrawPlus_S = function(vx, vy)
{
   this.buffer.moveTo(vx - 1,vy);
   this.buffer.lineTo(vx + 1,vy);
   this.buffer.moveTo(vx,vy - 1);
   this.buffer.lineTo(vx,vy + 1);
};
VectorRenderer.prototype.DrawPlusR = function(v, r)
{
   this.buffer.moveTo(v.x - r,v.y);
   this.buffer.lineTo(v.x + r,v.y);
   this.buffer.moveTo(v.x,v.y - r);
   this.buffer.lineTo(v.x,v.y + r);
};
VectorRenderer.prototype.DrawCross = function(v)
{
   this.buffer.moveTo(v.x - 1,v.y - 1);
   this.buffer.lineTo(v.x + 1,v.y + 1);
   this.buffer.moveTo(v.x + 1,v.y - 1);
   this.buffer.lineTo(v.x - 1,v.y + 1);
};
VectorRenderer.prototype.DrawCross_S = function(vx, vy)
{
   this.buffer.moveTo(vx - 1,vy - 1);
   this.buffer.lineTo(vx + 1,vy + 1);
   this.buffer.moveTo(vx + 1,vy - 1);
   this.buffer.lineTo(vx - 1,vy + 1);
};
VectorRenderer.prototype.DrawCrossR = function(v, r)
{
   this.buffer.moveTo(v.x - r,v.y - r);
   this.buffer.lineTo(v.x + r,v.y + r);
   this.buffer.moveTo(v.x + r,v.y - r);
   this.buffer.lineTo(v.x - r,v.y + r);
};
VectorRenderer.prototype.DrawCircle = function(v, r)
{
   var _loc4_ = v.x;
   var _loc3_ = v.y;
   this.buffer.moveTo(_loc4_ + r,_loc3_);
   this.buffer.curveTo(r + _loc4_,0.4142 * r + _loc3_,0.7071 * r + _loc4_,0.7071 * r + _loc3_);
   this.buffer.curveTo(0.4142 * r + _loc4_,r + _loc3_,_loc4_,r + _loc3_);
   this.buffer.curveTo(-0.4142 * r + _loc4_,r + _loc3_,-0.7071 * r + _loc4_,0.7071 * r + _loc3_);
   this.buffer.curveTo(- r + _loc4_,0.4142 * r + _loc3_,- r + _loc4_,_loc3_);
   this.buffer.curveTo(- r + _loc4_,-0.4142 * r + _loc3_,-0.7071 * r + _loc4_,-0.7071 * r + _loc3_);
   this.buffer.curveTo(-0.4142 * r + _loc4_,- r + _loc3_,_loc4_,- r + _loc3_);
   this.buffer.curveTo(0.4142 * r + _loc4_,- r + _loc3_,0.7071 * r + _loc4_,-0.7071 * r + _loc3_);
   this.buffer.curveTo(r + _loc4_,-0.4142 * r + _loc3_,r + _loc4_,_loc3_);
};
VectorRenderer.prototype.DrawCircle_S = function(x, y, r)
{
   this.buffer.moveTo(x + r,y);
   this.buffer.curveTo(r + x,0.4142 * r + y,0.7071 * r + x,0.7071 * r + y);
   this.buffer.curveTo(0.4142 * r + x,r + y,x,r + y);
   this.buffer.curveTo(-0.4142 * r + x,r + y,-0.7071 * r + x,0.7071 * r + y);
   this.buffer.curveTo(- r + x,0.4142 * r + y,- r + x,y);
   this.buffer.curveTo(- r + x,-0.4142 * r + y,-0.7071 * r + x,-0.7071 * r + y);
   this.buffer.curveTo(-0.4142 * r + x,- r + y,x,- r + y);
   this.buffer.curveTo(0.4142 * r + x,- r + y,0.7071 * r + x,-0.7071 * r + y);
   this.buffer.curveTo(r + x,-0.4142 * r + y,r + x,y);
};
VectorRenderer.prototype.DrawArc = function(p0, p1, c)
{
   this.buffer.moveTo(p0.x,p0.y);
   this.buffer.curveTo(c.x,c.y,p1.x,p1.y);
};
VectorRenderer.prototype.DrawArc_S = function(x0, y0, x1, y1, xc, yc)
{
   this.buffer.moveTo(x0,y0);
   this.buffer.curveTo(xc,yc,x1,y1);
};
VectorRenderer.prototype.DrawAABB = function(p, xw, yw)
{
   var _loc8_ = new Vector2(p.x + xw,p.y + yw);
   var _loc7_ = new Vector2(p.x - xw,p.y + yw);
   var _loc6_ = new Vector2(p.x - xw,p.y - yw);
   var _loc5_ = new Vector2(p.x + xw,p.y - yw);
   this.DrawQuad(_loc8_,_loc7_,_loc6_,_loc5_);
};
VectorRenderer.prototype.DrawAABB_S = function(minx, maxx, miny, maxy)
{
   var _loc5_ = new Vector2(maxx,maxy);
   var _loc4_ = new Vector2(minx,maxy);
   var _loc3_ = new Vector2(minx,miny);
   var _loc2_ = new Vector2(maxx,miny);
   this.DrawQuad(_loc5_,_loc4_,_loc3_,_loc2_);
};
VectorRenderer.prototype.DrawConcaveCCWArc_S = function(cx, cy, px, py)
{
   var _loc11_ = px;
   var _loc9_ = py;
   var _loc12_ = _loc11_ - cx;
   var _loc10_ = _loc9_ - cy;
   var _loc8_ = Math.sqrt(_loc12_ * _loc12_ + _loc10_ * _loc10_);
   var _loc17_ = _loc10_;
   var _loc16_ = - _loc12_;
   var _loc5_ = _loc11_ + _loc17_ - cx;
   var _loc4_ = _loc9_ + _loc16_ - cy;
   var _loc14_ = Math.sqrt(_loc5_ * _loc5_ + _loc4_ * _loc4_);
   _loc5_ /= _loc14_;
   _loc4_ /= _loc14_;
   _loc5_ *= _loc8_;
   _loc4_ *= _loc8_;
   _loc5_ += cx;
   _loc4_ += cy;
   var _loc7_ = (_loc11_ + _loc5_) * 0.5 - cx;
   var _loc6_ = (_loc9_ + _loc4_) * 0.5 - cy;
   var _loc13_ = Math.sqrt(_loc7_ * _loc7_ + _loc6_ * _loc6_);
   var _loc15_ = _loc8_ - _loc13_;
   _loc7_ /= _loc13_;
   _loc6_ /= _loc13_;
   _loc7_ *= _loc8_ + _loc15_;
   _loc6_ *= _loc8_ + _loc15_;
   _loc7_ += cx;
   _loc6_ += cy;
   this.buffer.moveTo(_loc11_,_loc9_);
   this.buffer.curveTo(_loc7_,_loc6_,_loc5_,_loc4_);
   _loc11_ = _loc5_;
   _loc9_ = _loc4_;
   _loc12_ = _loc11_ - cx;
   _loc10_ = _loc9_ - cy;
   _loc8_ = Math.sqrt(_loc12_ * _loc12_ + _loc10_ * _loc10_);
   _loc17_ = _loc10_;
   _loc16_ = - _loc12_;
   _loc5_ = _loc11_ + _loc17_ - cx;
   _loc4_ = _loc9_ + _loc16_ - cy;
   _loc14_ = Math.sqrt(_loc5_ * _loc5_ + _loc4_ * _loc4_);
   _loc5_ /= _loc14_;
   _loc4_ /= _loc14_;
   _loc5_ *= _loc8_;
   _loc4_ *= _loc8_;
   _loc5_ += cx;
   _loc4_ += cy;
   _loc7_ = (_loc11_ + _loc5_) * 0.5 - cx;
   _loc6_ = (_loc9_ + _loc4_) * 0.5 - cy;
   _loc13_ = Math.sqrt(_loc7_ * _loc7_ + _loc6_ * _loc6_);
   _loc15_ = _loc8_ - _loc13_;
   _loc7_ /= _loc13_;
   _loc6_ /= _loc13_;
   _loc7_ *= _loc8_ + _loc15_;
   _loc6_ *= _loc8_ + _loc15_;
   _loc7_ += cx;
   _loc6_ += cy;
   this.buffer.curveTo(_loc7_,_loc6_,_loc5_,_loc4_);
};
VectorRenderer.prototype.DrawLinestrip_nrope = function(vList)
{
   this.buffer.moveTo(vList[0].x,vList[0].y);
   var _loc2_ = 1;
   while(_loc2_ < vList.length)
   {
      this.buffer.lineTo(vList[_loc2_].x,vList[_loc2_].y);
      _loc2_ = _loc2_ + 1;
   }
};
