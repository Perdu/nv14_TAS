function CollideCirclevsTileMap(obj)
{
   var _loc3_ = obj.pos;
   var _loc4_ = obj.r;
   var _loc5_ = tiles.GetTile_V(_loc3_);
   var _loc6_ = _loc5_.pos.x;
   var _loc7_ = _loc5_.pos.y;
   var _loc8_ = _loc5_.xw;
   var _loc9_ = _loc5_.yw;
   var _loc10_ = _loc3_.x - _loc6_;
   var _loc11_ = _loc3_.y - _loc7_;
   var _loc12_;
   var _loc13_;
   _root.debugText.text = "";
   _root.resolveCircleText.text = "";
   if(0 < _loc5_.ID)
   {
      _loc12_ = _loc8_ + _loc4_ - Math.abs(_loc10_);
      _loc13_ = _loc9_ + _loc4_ - Math.abs(_loc11_);
      if(debug)
      {
         _root.debugText.text = "ResolveCircleTile: " + Math.round(Number(_loc12_) * 1000) / 1000 + ", " + Math.round(Number(_loc13_) * 1000) / 1000;
      }
      _root.resolveCircleText.text = Math.round(Number(_loc12_) * 1000) / 1000 + ", " + Math.round(Number(_loc13_) * 1000) / 1000;
      ResolveCircleTile(_loc12_,_loc13_,0,0,obj,_loc5_);
   }
   var _loc14_ = false;
   var _loc15_ = false;
   _loc11_ = _loc3_.y - _loc7_;
   _loc13_ = Math.abs(_loc11_) + _loc4_ - _loc9_;
   var _loc16_;
   var _loc17_;
   var _loc18_;
   if(0 < _loc13_)
   {
      _loc14_ = true;
      if(_loc11_ < 0)
      {
         _loc16_ = _loc5_.eU;
         _loc17_ = _loc5_.nU;
         _loc18_ = 1;
      }
      else
      {
         _loc16_ = _loc5_.eD;
         _loc17_ = _loc5_.nD;
         _loc18_ = -1;
      }
      if(0 < _loc16_)
      {
         if(_loc16_ == EID_SOLID)
         {
            _loc15_ = COL_AXIS;
            if(debug)
            {
               _root.debugText.text = "Vertical Penetration: " + _loc13_;
               trace("Vertical Penetration: " + _loc13_);
               trace("collision1: " + 0 + "," + _loc13_ * _loc18_ + "," + 0 + "," + _loc18_ + "," + _loc17_);
            }
            _root.debugText.text = "0, " + Math.round(Number(_loc13_ * _loc18_) * 1000) / 1000;
            obj.ReportCollisionVsWorld(0,_loc13_ * _loc18_,0,_loc18_,_loc17_);
         }
         else
         {
            _root.resolveCircleText.text = "0, " + Math.round(Number(_loc13_) * 1000) / 1000;
            _loc15_ = ResolveCircleTile(0,_loc13_,0,_loc18_,obj,_loc17_);
         }
      }
   }
   var _loc19_ = false;
   var _loc20_ = false;
   _loc10_ = _loc3_.x - _loc6_;
   _loc12_ = Math.abs(_loc10_) + _loc4_ - _loc8_;
   var _loc21_;
   var _loc22_;
   var _loc23_;
   if(0 < _loc12_)
   {
      _loc19_ = true;
      if(_loc10_ < 0)
      {
         _loc21_ = _loc5_.eL;
         _loc22_ = _loc5_.nL;
         _loc23_ = 1;
      }
      else
      {
         _loc21_ = _loc5_.eR;
         _loc22_ = _loc5_.nR;
         _loc23_ = -1;
      }
      if(0 < _loc21_)
      {
         if(_loc21_ == EID_SOLID)
         {
            _loc20_ = COL_AXIS;
            if(debug)
            {
               _root.debugText.text = "Horizontal Penetration: " + _loc12_;
               trace("Horizontal Penetration: " + _loc12_);
               trace("collision2: " + _loc12_ * _loc23_ + "," + 0 + "," + _loc23_ + "," + 0 + "," + _loc22_);
            }
            _root.debugText.text = Math.round(Number(_loc12_ * _loc23_) * 1000) / 1000 + ", 0";
            obj.ReportCollisionVsWorld(_loc12_ * _loc23_,0,_loc23_,0,_loc22_);
         }
         else
         {
            _root.resolveCircleText.text = Math.round(Number(_loc12_) * 1000) / 1000 + ", 0";
            _loc20_ = ResolveCircleTile(_loc12_,0,_loc23_,0,obj,_loc22_);
         }
      }
   }
   var _loc24_;
   var _loc25_;
   var _loc26_;
   var _loc27_;
   var _loc28_;
   var _loc29_;
   if(_loc19_ && _loc20_ != COL_AXIS && _loc14_ && _loc15_ != COL_AXIS)
   {
      _loc25_ = false;
      if(_loc10_ < 0 && _loc11_ < 0)
      {
         _loc21_ = _loc5_.nU.eL;
         _loc16_ = _loc5_.nL.eU;
         _loc24_ = _loc5_.nU.nL;
      }
      else if(_loc10_ < 0 && 0 < _loc11_)
      {
         _loc21_ = _loc5_.nD.eL;
         _loc16_ = _loc5_.nL.eD;
         _loc24_ = _loc5_.nD.nL;
      }
      else if(0 < _loc10_ && 0 < _loc11_)
      {
         _loc21_ = _loc5_.nD.eR;
         _loc16_ = _loc5_.nR.eD;
         _loc24_ = _loc5_.nD.nR;
      }
      else if(0 < _loc10_ && _loc11_ < 0)
      {
         _loc21_ = _loc5_.nU.eR;
         _loc16_ = _loc5_.nR.eU;
         _loc24_ = _loc5_.nU.nR;
      }
      if(0 < _loc21_ + _loc16_)
      {
         if(_loc21_ == EID_SOLID || _loc16_ == EID_SOLID)
         {
            _loc26_ = _loc24_.pos.x + _loc23_ * _loc24_.xw;
            _loc27_ = _loc24_.pos.y + _loc18_ * _loc24_.yw;
            _loc10_ = obj.pos.x - _loc26_;
            _loc11_ = obj.pos.y - _loc27_;
            _loc28_ = Math.sqrt(_loc10_ * _loc10_ + _loc11_ * _loc11_);
            _loc29_ = obj.r - _loc28_;
            if(0 < _loc29_)
            {
               if(_loc28_ == 0)
               {
                  _loc10_ = _loc23_ / 1.4142135623730951;
                  _loc11_ = _loc18_ / 1.4142135623730951;
               }
               else
               {
                  _loc10_ /= _loc28_;
                  _loc11_ /= _loc28_;
               }
               if(debug)
               {
                  trace("Corner Penetration: " + _loc29_);
                  _root.debugText.text = "Corner Penetration: " + Math.round(Number(_loc29_) * 1000) / 1000;
                  trace("collision3: " + _loc10_ * _loc29_ + "," + _loc11_ * _loc29_ + "," + _loc10_ + "," + _loc11_ + "," + _loc24_);
               }
               _root.debugText.text = Math.round(Number(_loc10_ * _loc29_) * 1000) / 1000 + ", " + Math.round(Number(_loc11_ * _loc29_) * 1000) / 1000;
               obj.ReportCollisionVsWorld(_loc10_ * _loc29_,_loc11_ * _loc29_,_loc10_,_loc11_,_loc24_);
            }
         }
         else
         {
            _loc10_ = _loc3_.x - _loc24_.pos.x;
            _loc11_ = _loc3_.y - _loc24_.pos.y;
            _loc12_ = Math.abs(_loc10_) + _loc4_ - _loc24_.xw;
            _loc13_ = Math.abs(_loc11_) + _loc4_ - _loc24_.yw;
            _root.resolveCircleText.text = Math.round(Number(_loc12_) * 1000) / 1000 + ", " + Math.round(Number(_loc13_) * 1000) / 1000;
            ResolveCircleTile(_loc12_,_loc13_,_loc23_,_loc18_,obj,_loc24_);
         }
      }
   }
}
if(_root.debugText == undefined)
{
   _root.createTextField("debugText",999999,400,3,100,20);
   _root.debugText.textColor = 0;
   _root.debugText.background = true;
   _root.debugText.backgroundColor = 16777215;
}
if(_root.resolveCircleText == undefined)
{
   _root.createTextField("resolveCircleText",999997,510,3,100,20);
   _root.resolveCircleText.textColor = 0;
   _root.resolveCircleText.background = true;
   _root.resolveCircleText.backgroundColor = 16777215;
}
