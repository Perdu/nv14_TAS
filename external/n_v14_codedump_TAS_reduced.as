movie 'D:\Documentos\N\Flash\n_v14.swf' {
// flash 6, total frames: 1, frame rate: 120 fps, 792x600 px, compressed


  /*
   * N v1.4 TAS/PHYSICS ANALYSIS DUMP
   *
   * Generated conservatively from n_v14_codedump.as.
   * Original SHA-256: d973c7c4f9a1297e5705fd8807687b6abcc4cd621bba5e38b5743dd685698bdb
   * Original size: 1604679 bytes; 24323 lines.
   *
   * Retention rule:
   *   Source bodies below are copied verbatim (apart from CRLF -> LF). Numeric
   *   constants, statement order, comparisons, object-list/grid behaviour,
   *   collision code, player/enemy logic, replay codecs, level/object parsing,
   *   and runtime tick order are not simplified or rewritten.
   *
   * Deliberately omitted:
   *   - embedded movie clips/buttons and other visual assets (original 3-2458)
   *   - VectorRenderer drawing implementation (2698-2950)
   *   - post-death ragdoll physics/rendering (10101-10868)
   *   - the editor (12442-14595)
   *   - built-in episode/help/menu level and demo payloads plus catalogue code
   *     (14596-16459); these are data, not simulation rules
   *   - user-profile persistence, online/filesystem code (16460-18242)
   *   - debug drawing, graphics-system implementation, GUI and console
   *     (18243-19578), except ParticleManager and NormToRot noted below
   *   - spider/menu/config/high-score application flows (19749-22996)
   *
   * ParticleManager is retained despite being visual because retained gameplay
   * calls it and its methods consume the shared Math.random() stream. Sound and
   * sprite calls embedded inside otherwise TAS-relevant methods remain verbatim;
   * their separate assets/implementations are omitted.
   *
   * This is an analysis corpus, not a standalone recompilable game: retained
   * code can still reference intentionally omitted visual, persistence, editor,
   * ragdoll, GUI, console, and application-menu symbols.
   *
   * Exact original line ranges retained after this header:
   *   2459-2697: Vector2 and keyboard/input state
   *   2951-10100: tile map, collision/raycasting, ObjectManager, game objects, player core
   *   10869-12441: player state/physics, NinjaGame, level/replay codecs and loaders
   *   18379-18808: particle calls (retained for exact global RNG consumption)
   *   18923-18935: normal-to-rotation helpers called from retained gameplay code
   *   19579-19748: application tick/input loop and module construction order
   *   22997-24323: gameplay/replay timing, debug/custom play, level loading, constants/init
   */

  // ===== RETAINED ORIGINAL LINES 2459-2697: Vector2 and keyboard/input state =====
  frame 1 {
    function Vector2(x, y) {
      this.x = x;
      this.y = y;
    }

    Vector2.prototype.ToString = function () {
      return '(' + this.x + ',' + this.y + ')';
    };

    Vector2.prototype.clone = function () {
      var v2 = new Vector2(this.x, this.y);
      return v2;
    };

    Vector2.prototype.plus = function (v2) {
      var v2 = new Vector2(this.x + v2.x, this.y + v2.y);
      return v2;
    };

    Vector2.prototype.minus = function (v2) {
      var v2 = new Vector2(this.x - v2.x, this.y - v2.y);
      return v2;
    };

    Vector2.prototype.normR = function () {
      var v2 = new Vector2(this.y * -1, this.x);
      return v2;
    };

    Vector2.prototype.dir = function () {
      var v2 = this.clone();
      v2.normalize();
      return v2;
    };

    Vector2.prototype.proj = function (v2) {
      var v3 = v2.dot(v2);
      if (v3 == 0) {
        var v2 = this.clone();
        return v2;
      }
      v2 = v2.clone();
      v2.mult(this.dot(v2) / v3);
      return v2;
    };

    Vector2.prototype.projLen = function (v2) {
      var v2 = v2.dot(v2);
      if (v2 == 0) {
        return 0;
      } else {
        return Math.abs(this.dot(v2) / v2);
      }
    };

    Vector2.prototype.dot = function (v2) {
      return this.x * v2.x + this.y * v2.y;
    };

    Vector2.prototype.cross = function (v2) {
      return this.x * v2.y - this.y * v2.x;
    };

    Vector2.prototype.len = function () {
      return Math.sqrt(this.x * this.x + this.y * this.y);
    };

    Vector2.prototype.copy = function (v2) {
      this.x = v2.x;
      this.y = v2.y;
    };

    Vector2.prototype.mult = function (s) {
      this.x *= s;
      this.y *= s;
    };

    Vector2.prototype.normalize = function () {
      var v2 = this.len();
      if (v2 != 0) {
        this.x /= v2;
        this.y /= v2;
      } else {}
    };

    Vector2.prototype.pluseq = function (v2) {
      this.x += v2.x;
      this.y += v2.y;
    };

    Vector2.prototype.minuseq = function (v2) {
      this.x -= v2.x;
      this.y -= v2.y;
    };

  }

  frame 1 {
    function InputManager() {
      this.vrend = new VectorRenderer();
      this.mPos = new Vector2(this.vrend.buffer._xmouse, this.vrend.buffer._ymouse);
      this.mOldpos = new Vector2(this.vrend.buffer._xmouse, this.vrend.buffer._ymouse);
      this.mDelta = new Vector2(0, 0);
      this.mDownPos = new Vector2(0, 0);
      this.mUpPos = new Vector2(0, 0);
      this.onMouseDown = this.CaptureMouseDown;
      this.onMouseUp = this.CaptureMouseUp;
      Mouse.addListener(this);
      this.mState = false;
      this.mOldState = false;
      this.mPressed = false;
      this.mReleased = false;
      this.kCode = new Array();
      this.kState = new Array();
      this.kOldState = new Array();
      this.tKey = new Array();
      this.tState = new Array();
    }

    InputManager.prototype.RegisterKey = function (knum) {
      var v2 = this.kCode.length;
      this.kCode.push(knum);
      this.kState[v2] = false;
      this.kOldState[v2] = false;
      return v2;
    };

    InputManager.prototype.RegisterToggle = function (knum) {
      var v2 = this.tKey.length;
      this.tKey.push(this.RegisterKey(knum));
      this.tState[v2] = false;
      return v2;
    };

    InputManager.prototype.Update = function () {
      this.mOldpos.x = this.mPos.x;
      this.mOldpos.y = this.mPos.y;
      this.mPos.x = this.vrend.buffer._xmouse;
      this.mPos.y = this.vrend.buffer._ymouse;
      this.mDelta.x = this.mPos.x - this.mOldpos.x;
      this.mDelta.y = this.mPos.y - this.mOldpos.y;
      if (this.mState && !this.mOldState) {
        this.mPressed = true;
        this.mOldState = true;
        this.mDownPos.x = this.mPos.x;
        this.mDownPos.y = this.mPos.y;
      } else {
        this.mPressed = false;
      }
      if (!this.mState && this.mOldState) {
        this.mReleased = true;
        this.mOldState = false;
        this.mUpPos.x = this.mPos.x;
        this.mUpPos.y = this.mPos.y;
      } else {
        this.mReleased = false;
      }
      if (this.mState) {
        this.mUpPos.x = this.mPos.x;
        this.mUpPos.y = this.mPos.y;
      }
      var v2 = 0;
      while (v2 < this.kCode.length) {
        this.kOldState[v2] = Key.isDown(this.kCode[v2]);
        ++v2;
      }
      var v3 = this.kOldState;
      this.kOldState = this.kState;
      this.kState = v3;
      v2 = 0;
      while (v2 < this.tKey.length) {
        if (this.Pressed(this.tKey[v2])) {
          this.tState[v2] = !this.tState[v2];
        }
        ++v2;
      }
    };

    InputManager.prototype.CaptureMouseDown = function () {
      this.mOldState = false;
      this.mState = true;
    };

    InputManager.prototype.CaptureMouseUp = function () {
      this.mOldState = true;
      this.mState = false;
    };

    InputManager.prototype.getMousePos = function () {
      return this.mPos.clone();
    };

    InputManager.prototype.getMouseDelta = function () {
      return this.mDelta.clone();
    };

    InputManager.prototype.getMouseDragDelta = function () {
      return this.mUpPos.minus(this.mDownPos);
    };

    InputManager.prototype.getMouseDownPos = function () {
      return this.mDownPos.clone();
    };

    InputManager.prototype.getMouseUpPos = function () {
      return this.mUpPos.clone();
    };

    InputManager.prototype.MousePressed = function () {
      return this.mPressed;
    };

    InputManager.prototype.MouseReleased = function () {
      return this.mReleased;
    };

    InputManager.prototype.MouseDown = function () {
      return this.mState;
    };

    InputManager.prototype.Down = function (knum) {
      return this.kState[knum];
    };

    InputManager.prototype.Pressed = function (knum) {
      return this.kState[knum] && !this.kOldState[knum];
    };

    InputManager.prototype.Released = function (knum) {
      return !this.kState[knum] && this.kOldState[knum];
    };

    InputManager.prototype.Toggled = function (tnum) {
      return this.tState[tnum];
    };

  }


  // ===== RETAINED ORIGINAL LINES 2951-10100: tile map, collision/raycasting, ObjectManager, game objects, player core =====
  frame 1 {
    function TileMap(rows, cols, xw, yw) {
      this.xw = xw;
      this.yw = yw;
      this.tw = 2 * this.xw;
      this.th = 2 * this.yw;
      this.rows = rows;
      this.cols = cols;
      this.fullrows = this.rows + 2;
      this.fullcols = this.cols + 2;
      this.minX = this.tw;
      this.minY = this.th;
      this.maxX = this.tw + rows * this.tw;
      this.maxY = this.th + cols * this.th;
      this.grid = new Object();
      this.BUILD_STEPS_REMAINING = 9;
      this.rend = new VectorRenderer();
      this.rend.Clear();
    }

    TileMap.prototype.Building = function () {
      var v7 = this.xw;
      var v5 = this.yw;
      var v4 = this.fullrows;
      var v2 = this.fullcols;
      var v8 = this.rows;
      var v9 = this.cols;
      if (this.BUILD_STEPS_REMAINING == 9) {
        var v6 = 0;
        while (v6 < v4) {
          this.grid[v6] = new Object();
          var v3 = 0;
          while (v3 < v2) {
            this.grid[v6][v3] = new TileMapCell(v6, v3, v7, v5, this.xw, this.yw);
            v5 += this.th;
            ++v3;
          }
          v7 += this.tw;
          v5 = this.yw;
          ++v6;
        }
        --this.BUILD_STEPS_REMAINING;
        return true;
      } else {
        if (this.BUILD_STEPS_REMAINING == 8) {
          var v6 = 0;
          while (v6 < v4 - 1) {
            var v3 = 0;
            while (v3 < v2) {
              this.grid[v6][v3].LinkR(this.grid[v6 + 1][v3]);
              ++v3;
            }
            ++v6;
          }
          --this.BUILD_STEPS_REMAINING;
          return true;
        } else {
          if (this.BUILD_STEPS_REMAINING == 7) {
            var v6 = 1;
            while (v6 < v4) {
              var v3 = 0;
              while (v3 < v2) {
                this.grid[v6][v3].LinkL(this.grid[v6 - 1][v3]);
                ++v3;
              }
              ++v6;
            }
            --this.BUILD_STEPS_REMAINING;
            return true;
          } else {
            if (this.BUILD_STEPS_REMAINING == 6) {
              var v6 = 0;
              while (v6 < v4) {
                var v3 = 0;
                while (v3 < v2 - 1) {
                  this.grid[v6][v3].LinkD(this.grid[v6][v3 + 1]);
                  ++v3;
                }
                ++v6;
              }
              --this.BUILD_STEPS_REMAINING;
              return true;
            } else {
              if (this.BUILD_STEPS_REMAINING == 5) {
                var v6 = 0;
                while (v6 < v4) {
                  var v3 = 1;
                  while (v3 < v2) {
                    this.grid[v6][v3].LinkU(this.grid[v6][v3 - 1]);
                    ++v3;
                  }
                  ++v6;
                }
                --this.BUILD_STEPS_REMAINING;
                return true;
              } else {
                if (this.BUILD_STEPS_REMAINING == 4) {
                  var v6 = 0;
                  while (v6 < v4) {
                    this.grid[v6][0].SetState(TID_FULL);
                    ++v6;
                  }
                  --this.BUILD_STEPS_REMAINING;
                  return true;
                } else {
                  if (this.BUILD_STEPS_REMAINING == 3) {
                    var v6 = 0;
                    while (v6 < v4) {
                      this.grid[v6][v2 - 1].SetState(TID_FULL);
                      ++v6;
                    }
                    --this.BUILD_STEPS_REMAINING;
                    return true;
                  } else {
                    if (this.BUILD_STEPS_REMAINING == 2) {
                      var v6 = 0;
                      while (v6 < v2) {
                        this.grid[0][v6].SetState(TID_FULL);
                        ++v6;
                      }
                      --this.BUILD_STEPS_REMAINING;
                      return true;
                    } else {
                      if (this.BUILD_STEPS_REMAINING == 1) {
                        var v6 = 0;
                        while (v6 < v2) {
                          this.grid[v4 - 1][v6].SetState(TID_FULL);
                          ++v6;
                        }
                        --this.BUILD_STEPS_REMAINING;
                        return true;
                      } else {
                        return false;
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    };

    TileMap.prototype.ClearGrid = function () {
      var v2;
      for (var v4 in this.grid) {
        v2 = this.grid[v4];
        for (var v3 in v2) {
          v2[v3].next = null;
          v2[v3].prev = null;
        }
      }
    };

    TileMap.prototype.GetTile_S = function (x, y) {
      return this.grid[Math.floor(x / this.tw)][Math.floor(y / this.th)];
    };

    TileMap.prototype.GetTile_V = function (p) {
      return this.grid[Math.floor(p.x / this.tw)][Math.floor(p.y / this.th)];
    };

    TileMap.prototype.GetTile_I = function (i, j) {
      return this.grid[i][j];
    };

    TileMap.prototype.GetIndex_S = function (v, x, y) {
      v.x = Math.floor(x / this.tw);
      v.y = Math.floor(y / this.th);
    };

    TileMap.prototype.GetIndex_V = function (v, p) {
      v.x = Math.floor(p.x / this.tw);
      v.y = Math.floor(p.y / this.th);
    };

  }

  frame 1 {
    function TileMapCell(i, j, x, y, xw, yw) {
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
      this.pos = new Vector2(x, y);
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
      var v2 = false;
      if (!v2) {
        this.mc = gfx.CreateSprite('tileMC', LAYER_TILES);
        this.mc.gotoAndStop(1);
        this.mc._xscale = this.xw * 2;
        this.mc._yscale = this.yw * 2;
        this.mc._x = this.pos.x;
        this.mc._y = this.pos.y;
        var v3 = new Color(this.mc);
        v3.setRGB(7960968);
      } else {
        this.mc = gfx.CreateSprite('tileMC2', LAYER_TILES2);
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
    TileMapCell.prototype.LinkU = function (t) {
      this.nU = t;
    };

    TileMapCell.prototype.LinkD = function (t) {
      this.nD = t;
    };

    TileMapCell.prototype.LinkL = function (t) {
      this.nL = t;
    };

    TileMapCell.prototype.LinkR = function (t) {
      this.nR = t;
    };

    TileMapCell.prototype.ToString = function () {
      var v2 = '(' + this.i + ',' + this.j + ')';
      return v2;
    };

    TileMapCell.prototype.Draw = function () {
      this.mc.gotoAndStop(this.ID + 1);
    };

  }

  frame 1 {
    TileMapCell.prototype.SetState = function (ID) {
      if (ID == TID_EMPTY) {
        this.Clear();
      } else {
        this.ID = ID;
        this.UpdateType();
        this.UpdateEdges();
        this.UpdateNeighbors();
      }
    };

    TileMapCell.prototype.Clear = function () {
      this.ID = TID_EMPTY;
      this.UpdateType();
      this.UpdateEdges();
      this.UpdateNeighbors();
      this.Draw();
    };

    TileMapCell.prototype.UpdateNeighbors = function () {
      if (this.nU != null) {
        this.nU.UpdateEdges();
      }
      if (this.nD != null) {
        this.nD.UpdateEdges();
      }
      if (this.nL != null) {
        this.nL.UpdateEdges();
      }
      if (this.nR != null) {
        this.nR.UpdateEdges();
      }
    };

    TileMapCell.prototype.UpdateType = function () {
      if (0 < this.ID) {
        if (this.ID < CTYPE_45DEG) {
          this.CTYPE = CTYPE_FULL;
          this.signx = 0;
          this.signy = 0;
          this.sx = 0;
          this.sy = 0;
        } else {
          if (this.ID < CTYPE_CONCAVE) {
            this.CTYPE = CTYPE_45DEG;
            if (this.ID == TID_45DEGpn) {
              this.signx = 1;
              this.signy = -1;
              this.sx = this.signx / Math.SQRT2;
              this.sy = this.signy / Math.SQRT2;
            } else {
              if (this.ID == TID_45DEGnn) {
                this.signx = -1;
                this.signy = -1;
                this.sx = this.signx / Math.SQRT2;
                this.sy = this.signy / Math.SQRT2;
              } else {
                if (this.ID == TID_45DEGnp) {
                  this.signx = -1;
                  this.signy = 1;
                  this.sx = this.signx / Math.SQRT2;
                  this.sy = this.signy / Math.SQRT2;
                } else {
                  if (this.ID == TID_45DEGpp) {
                    this.signx = 1;
                    this.signy = 1;
                    this.sx = this.signx / Math.SQRT2;
                    this.sy = this.signy / Math.SQRT2;
                  } else {
                    return false;
                  }
                }
              }
            }
          } else {
            if (this.ID < CTYPE_CONVEX) {
              this.CTYPE = CTYPE_CONCAVE;
              if (this.ID == TID_CONCAVEpn) {
                this.signx = 1;
                this.signy = -1;
                this.sx = 0;
                this.sy = 0;
              } else {
                if (this.ID == TID_CONCAVEnn) {
                  this.signx = -1;
                  this.signy = -1;
                  this.sx = 0;
                  this.sy = 0;
                } else {
                  if (this.ID == TID_CONCAVEnp) {
                    this.signx = -1;
                    this.signy = 1;
                    this.sx = 0;
                    this.sy = 0;
                  } else {
                    if (this.ID == TID_CONCAVEpp) {
                      this.signx = 1;
                      this.signy = 1;
                      this.sx = 0;
                      this.sy = 0;
                    } else {
                      return false;
                    }
                  }
                }
              }
            } else {
              if (this.ID < CTYPE_22DEGs) {
                this.CTYPE = CTYPE_CONVEX;
                if (this.ID == TID_CONVEXpn) {
                  this.signx = 1;
                  this.signy = -1;
                  this.sx = 0;
                  this.sy = 0;
                } else {
                  if (this.ID == TID_CONVEXnn) {
                    this.signx = -1;
                    this.signy = -1;
                    this.sx = 0;
                    this.sy = 0;
                  } else {
                    if (this.ID == TID_CONVEXnp) {
                      this.signx = -1;
                      this.signy = 1;
                      this.sx = 0;
                      this.sy = 0;
                    } else {
                      if (this.ID == TID_CONVEXpp) {
                        this.signx = 1;
                        this.signy = 1;
                        this.sx = 0;
                        this.sy = 0;
                      } else {
                        return false;
                      }
                    }
                  }
                }
              } else {
                if (this.ID < CTYPE_22DEGb) {
                  this.CTYPE = CTYPE_22DEGs;
                  if (this.ID == TID_22DEGpnS) {
                    this.signx = 1;
                    this.signy = -1;
                    var v2 = 2.23606797749979;
                    this.sx = this.signx * 1 / v2;
                    this.sy = this.signy * 2 / v2;
                  } else {
                    if (this.ID == TID_22DEGnnS) {
                      this.signx = -1;
                      this.signy = -1;
                      var v2 = 2.23606797749979;
                      this.sx = this.signx * 1 / v2;
                      this.sy = this.signy * 2 / v2;
                    } else {
                      if (this.ID == TID_22DEGnpS) {
                        this.signx = -1;
                        this.signy = 1;
                        var v2 = 2.23606797749979;
                        this.sx = this.signx * 1 / v2;
                        this.sy = this.signy * 2 / v2;
                      } else {
                        if (this.ID == TID_22DEGppS) {
                          this.signx = 1;
                          this.signy = 1;
                          var v2 = 2.23606797749979;
                          this.sx = this.signx * 1 / v2;
                          this.sy = this.signy * 2 / v2;
                        } else {
                          return false;
                        }
                      }
                    }
                  }
                } else {
                  if (this.ID < CTYPE_67DEGs) {
                    this.CTYPE = CTYPE_22DEGb;
                    if (this.ID == TID_22DEGpnB) {
                      this.signx = 1;
                      this.signy = -1;
                      var v2 = 2.23606797749979;
                      this.sx = this.signx * 1 / v2;
                      this.sy = this.signy * 2 / v2;
                    } else {
                      if (this.ID == TID_22DEGnnB) {
                        this.signx = -1;
                        this.signy = -1;
                        var v2 = 2.23606797749979;
                        this.sx = this.signx * 1 / v2;
                        this.sy = this.signy * 2 / v2;
                      } else {
                        if (this.ID == TID_22DEGnpB) {
                          this.signx = -1;
                          this.signy = 1;
                          var v2 = 2.23606797749979;
                          this.sx = this.signx * 1 / v2;
                          this.sy = this.signy * 2 / v2;
                        } else {
                          if (this.ID == TID_22DEGppB) {
                            this.signx = 1;
                            this.signy = 1;
                            var v2 = 2.23606797749979;
                            this.sx = this.signx * 1 / v2;
                            this.sy = this.signy * 2 / v2;
                          } else {
                            return false;
                          }
                        }
                      }
                    }
                  } else {
                    if (this.ID < CTYPE_67DEGb) {
                      this.CTYPE = CTYPE_67DEGs;
                      if (this.ID == TID_67DEGpnS) {
                        this.signx = 1;
                        this.signy = -1;
                        var v2 = 2.23606797749979;
                        this.sx = this.signx * 2 / v2;
                        this.sy = this.signy * 1 / v2;
                      } else {
                        if (this.ID == TID_67DEGnnS) {
                          this.signx = -1;
                          this.signy = -1;
                          var v2 = 2.23606797749979;
                          this.sx = this.signx * 2 / v2;
                          this.sy = this.signy * 1 / v2;
                        } else {
                          if (this.ID == TID_67DEGnpS) {
                            this.signx = -1;
                            this.signy = 1;
                            var v2 = 2.23606797749979;
                            this.sx = this.signx * 2 / v2;
                            this.sy = this.signy * 1 / v2;
                          } else {
                            if (this.ID == TID_67DEGppS) {
                              this.signx = 1;
                              this.signy = 1;
                              var v2 = 2.23606797749979;
                              this.sx = this.signx * 2 / v2;
                              this.sy = this.signy * 1 / v2;
                            } else {
                              return false;
                            }
                          }
                        }
                      }
                    } else {
                      if (this.ID < CTYPE_HALF) {
                        this.CTYPE = CTYPE_67DEGb;
                        if (this.ID == TID_67DEGpnB) {
                          this.signx = 1;
                          this.signy = -1;
                          var v2 = 2.23606797749979;
                          this.sx = this.signx * 2 / v2;
                          this.sy = this.signy * 1 / v2;
                        } else {
                          if (this.ID == TID_67DEGnnB) {
                            this.signx = -1;
                            this.signy = -1;
                            var v2 = 2.23606797749979;
                            this.sx = this.signx * 2 / v2;
                            this.sy = this.signy * 1 / v2;
                          } else {
                            if (this.ID == TID_67DEGnpB) {
                              this.signx = -1;
                              this.signy = 1;
                              var v2 = 2.23606797749979;
                              this.sx = this.signx * 2 / v2;
                              this.sy = this.signy * 1 / v2;
                            } else {
                              if (this.ID == TID_67DEGppB) {
                                this.signx = 1;
                                this.signy = 1;
                                var v2 = 2.23606797749979;
                                this.sx = this.signx * 2 / v2;
                                this.sy = this.signy * 1 / v2;
                              } else {
                                return false;
                              }
                            }
                          }
                        }
                      } else {
                        this.CTYPE = CTYPE_HALF;
                        if (this.ID == TID_HALFd) {
                          this.signx = 0;
                          this.signy = -1;
                          this.sx = this.signx;
                          this.sy = this.signy;
                        } else {
                          if (this.ID == TID_HALFu) {
                            this.signx = 0;
                            this.signy = 1;
                            this.sx = this.signx;
                            this.sy = this.signy;
                          } else {
                            if (this.ID == TID_HALFl) {
                              this.signx = 1;
                              this.signy = 0;
                              this.sx = this.signx;
                              this.sy = this.signy;
                            } else {
                              if (this.ID == TID_HALFr) {
                                this.signx = -1;
                                this.signy = 0;
                                this.sx = this.signx;
                                this.sy = this.signy;
                              } else {
                                return false;
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
      } else {
        this.CTYPE = CTYPE_EMPTY;
        this.signx = 0;
        this.signy = 0;
        this.sx = 0;
        this.sy = 0;
      }
    };

  }

  frame 1 {
    TileMapCell.prototype.UpdateEdges = function () {
      var v2 = this.nU;
      if (this.ID == TID_EMPTY) {
        if (v2.ID == TID_EMPTY) {
          this.eU = EID_OFF;
        } else {
          if (v2.ID == TID_FULL) {
            this.eU = EID_SOLID;
          } else {
            if (v2.signy * -1 <= 0 || v2.ID == TID_67DEGpnS || v2.ID == TID_67DEGnnS) {
              this.eU = EID_INTERESTING;
            } else {
              this.eU = EID_SOLID;
            }
          }
        }
      } else {
        if (this.ID == TID_FULL) {
          if (v2.ID == TID_FULL) {
            this.eU = EID_OFF;
          } else {
            if (v2.ID == TID_EMPTY) {
              this.eU = EID_OFF;
            } else {
              if (v2.signy * -1 <= 0 || v2.ID == TID_67DEGpnS || v2.ID == TID_67DEGnnS) {
                this.eU = EID_INTERESTING;
              } else {
                this.eU = EID_OFF;
              }
            }
          }
        } else {
          if (0 <= this.signy * -1) {
            if (v2.ID == TID_EMPTY) {
              this.eU = EID_OFF;
            } else {
              if (v2.ID == TID_FULL) {
                this.eU = EID_SOLID;
              } else {
                if (v2.signy * -1 <= 0 || v2.ID == TID_67DEGpnS || v2.ID == TID_67DEGnnS) {
                  this.eU = EID_INTERESTING;
                } else {
                  this.eU = EID_SOLID;
                }
              }
            }
          } else {
            if (this.ID == TID_67DEGppS || this.ID == TID_67DEGnpS) {
              if (v2.ID == TID_EMPTY) {
                this.eU = EID_OFF;
              } else {
                if (v2.ID == TID_FULL) {
                  this.eU = EID_SOLID;
                } else {
                  if (v2.signy * -1 <= 0 || v2.ID == TID_67DEGpnS || v2.ID == TID_67DEGnnS) {
                    this.eU = EID_INTERESTING;
                  } else {
                    if (0 < v2.signy * -1 || v2.ID == TID_FULL) {
                      this.eU = EID_SOLID;
                    } else {
                      this.eU = EID_OFF;
                    }
                  }
                }
              }
            } else {
              if (v2.ID == TID_FULL) {
                this.eU = EID_OFF;
              } else {
                if (v2.ID == TID_EMPTY) {
                  this.eU = EID_OFF;
                } else {
                  if (v2.signy * -1 <= 0 || v2.ID == TID_67DEGpnS || v2.ID == TID_67DEGnnS) {
                    this.eU = EID_INTERESTING;
                  } else {
                    this.eU = EID_OFF;
                  }
                }
              }
            }
          }
        }
      }
      v2 = this.nD;
      if (this.ID == TID_EMPTY) {
        if (v2.ID == TID_EMPTY) {
          this.eD = EID_OFF;
        } else {
          if (v2.ID == TID_FULL) {
            this.eD = EID_SOLID;
          } else {
            if (v2.signy * 1 <= 0 || v2.ID == TID_67DEGppS || v2.ID == TID_67DEGnpS) {
              this.eD = EID_INTERESTING;
            } else {
              this.eD = EID_SOLID;
            }
          }
        }
      } else {
        if (this.ID == TID_FULL) {
          if (v2.ID == TID_FULL) {
            this.eD = EID_OFF;
          } else {
            if (v2.ID == TID_EMPTY) {
              this.eD = EID_OFF;
            } else {
              if (v2.signy * 1 <= 0 || v2.ID == TID_67DEGppS || v2.ID == TID_67DEGnpS) {
                this.eD = EID_INTERESTING;
              } else {
                this.eD = EID_OFF;
              }
            }
          }
        } else {
          if (0 <= this.signy * 1) {
            if (v2.ID == TID_EMPTY) {
              this.eD = EID_OFF;
            } else {
              if (v2.ID == TID_FULL) {
                this.eD = EID_SOLID;
              } else {
                if (v2.signy * 1 <= 0 || v2.ID == TID_67DEGppS || v2.ID == TID_67DEGnpS) {
                  this.eD = EID_INTERESTING;
                } else {
                  this.eD = EID_SOLID;
                }
              }
            }
          } else {
            if (this.ID == TID_67DEGpnS || this.ID == TID_67DEGnnS) {
              if (v2.ID == TID_EMPTY) {
                this.eD = EID_OFF;
              } else {
                if (v2.ID == TID_FULL) {
                  this.eD = EID_SOLID;
                } else {
                  if (v2.signy * 1 <= 0 || v2.ID == TID_67DEGppS || v2.ID == TID_67DEGnpS) {
                    this.eD = EID_INTERESTING;
                  } else {
                    if (0 < v2.signy * 1 || v2.ID == TID_FULL) {
                      this.eD = EID_SOLID;
                    } else {
                      this.eD = EID_OFF;
                    }
                  }
                }
              }
            } else {
              if (v2.ID == TID_FULL) {
                this.eD = EID_OFF;
              } else {
                if (v2.ID == TID_EMPTY) {
                  this.eD = EID_OFF;
                } else {
                  if (v2.signy * 1 <= 0 || v2.ID == TID_67DEGppS || v2.ID == TID_67DEGnpS) {
                    this.eD = EID_INTERESTING;
                  } else {
                    this.eD = EID_OFF;
                  }
                }
              }
            }
          }
        }
      }
      v2 = this.nR;
      if (this.ID == TID_EMPTY) {
        if (v2.ID == TID_EMPTY) {
          this.eR = EID_OFF;
        } else {
          if (v2.ID == TID_FULL) {
            this.eR = EID_SOLID;
          } else {
            if (v2.signx * 1 <= 0 || v2.ID == TID_22DEGpnS || v2.ID == TID_22DEGppS) {
              this.eR = EID_INTERESTING;
            } else {
              this.eR = EID_SOLID;
            }
          }
        }
      } else {
        if (this.ID == TID_FULL) {
          if (v2.ID == TID_FULL) {
            this.eR = EID_OFF;
          } else {
            if (v2.ID == TID_EMPTY) {
              this.eR = EID_OFF;
            } else {
              if (v2.signx * 1 <= 0 || v2.ID == TID_22DEGpnS || v2.ID == TID_22DEGppS) {
                this.eR = EID_INTERESTING;
              } else {
                this.eR = EID_OFF;
              }
            }
          }
        } else {
          if (0 <= this.signx * 1) {
            if (v2.ID == TID_EMPTY) {
              this.eR = EID_OFF;
            } else {
              if (v2.ID == TID_FULL) {
                this.eR = EID_SOLID;
              } else {
                if (v2.signx * 1 <= 0 || v2.ID == TID_22DEGpnS || v2.ID == TID_22DEGppS) {
                  this.eR = EID_INTERESTING;
                } else {
                  this.eR = EID_SOLID;
                }
              }
            }
          } else {
            if (this.ID == TID_22DEGnnS || this.ID == TID_22DEGnpS) {
              if (v2.ID == TID_EMPTY) {
                this.eR = EID_OFF;
              } else {
                if (v2.ID == TID_FULL) {
                  this.eR = EID_SOLID;
                } else {
                  if (v2.signx * 1 <= 0 || v2.ID == TID_22DEGpnS || v2.ID == TID_22DEGppS) {
                    this.eR = EID_INTERESTING;
                  } else {
                    if (v2.ID == TID_FULL || 0 < v2.signx * 1) {
                      this.eR = EID_SOLID;
                    } else {
                      this.eR = EID_OFF;
                    }
                  }
                }
              }
            } else {
              if (v2.ID == TID_FULL) {
                this.eR = EID_OFF;
              } else {
                if (v2.ID == TID_EMPTY) {
                  this.eR = EID_OFF;
                } else {
                  if (v2.signx * 1 <= 0 || v2.ID == TID_22DEGpnS || v2.ID == TID_22DEGppS) {
                    this.eR = EID_INTERESTING;
                  } else {
                    this.eR = EID_OFF;
                  }
                }
              }
            }
          }
        }
      }
      v2 = this.nL;
      if (this.ID == TID_EMPTY) {
        if (v2.ID == TID_EMPTY) {
          this.eL = EID_OFF;
        } else {
          if (v2.ID == TID_FULL) {
            this.eL = EID_SOLID;
          } else {
            if (v2.signx * -1 <= 0 || v2.ID == TID_22DEGnnS || v2.ID == TID_22DEGnpS) {
              this.eL = EID_INTERESTING;
            } else {
              this.eL = EID_SOLID;
            }
          }
        }
      } else {
        if (this.ID == TID_FULL) {
          if (v2.ID == TID_FULL) {
            this.eL = EID_OFF;
          } else {
            if (v2.ID == TID_EMPTY) {
              this.eL = EID_OFF;
            } else {
              if (v2.signx * -1 <= 0 || v2.ID == TID_22DEGnnS || v2.ID == TID_22DEGnpS) {
                this.eL = EID_INTERESTING;
              } else {
                this.eL = EID_OFF;
              }
            }
          }
        } else {
          if (0 <= this.signx * -1) {
            if (v2.ID == TID_EMPTY) {
              this.eL = EID_OFF;
            } else {
              if (v2.ID == TID_FULL) {
                this.eL = EID_SOLID;
              } else {
                if (v2.signx * -1 <= 0 || v2.ID == TID_22DEGnnS || v2.ID == TID_22DEGnpS) {
                  this.eL = EID_INTERESTING;
                } else {
                  this.eL = EID_SOLID;
                }
              }
            }
          } else {
            if (this.ID == TID_22DEGpnS || this.ID == TID_22DEGppS) {
              if (v2.ID == TID_EMPTY) {
                this.eL = EID_OFF;
              } else {
                if (v2.ID == TID_FULL) {
                  this.eL = EID_SOLID;
                } else {
                  if (v2.signx * -1 <= 0 || v2.ID == TID_22DEGnnS || v2.ID == TID_22DEGnpS) {
                    this.eL = EID_INTERESTING;
                  } else {
                    if (0 < v2.signx * -1 || v2.ID == TID_FULL) {
                      this.eL = EID_SOLID;
                    } else {
                      this.eL = EID_OFF;
                    }
                  }
                }
              }
            } else {
              if (v2.ID == TID_FULL) {
                this.eL = EID_OFF;
              } else {
                if (v2.ID == TID_EMPTY) {
                  this.eL = EID_OFF;
                } else {
                  if (v2.signx * -1 <= 0 || v2.ID == TID_22DEGnnS || v2.ID == TID_22DEGnpS) {
                    this.eL = EID_INTERESTING;
                  } else {
                    this.eL = EID_OFF;
                  }
                }
              }
            }
          }
        }
      }
      this.Draw();
    };

  }

  frame 1 {
    TileMapCell.prototype.InsertObj = function (obj) {
      obj.next = this.next;
      obj.prev = this;
      this.prev = null;
      if (this.next != null) {
        this.next.prev = obj;
      }
      this.next = obj;
      ++this.objcounter;
    };

    TileMapCell.prototype.RemoveObj = function (obj) {
      obj.prev.next = obj.next;
      if (obj.next != null) {
        obj.next.prev = obj.prev;
      }
      obj.next = null;
      obj.prev = null;
      --this.objcounter;
    };

  }

  frame 1 {
    CHAR_PAD = 48;
    TileMap.prototype.GetTileStates = function () {
      var v8 = this.rows;
      var v6 = this.cols;
      var v7 = this.grid;
      var v5 = '';
      var v4;
      var v3 = 0;
      while (v3 < v8) {
        v4 = v7[v3 + 1];
        var v2 = 0;
        while (v2 < v6) {
          v5 += String.fromCharCode(v4[v2 + 1].ID + CHAR_PAD);
          ++v2;
        }
        ++v3;
      }
      return v5;
    };

    TileMap.prototype.SetTileState = function (i, j, char) {
      this.grid[i + 1][j + 1].SetState(char - CHAR_PAD);
    };

    TileMap.prototype.SetTileStates = function (instr) {
      var v8 = this.rows;
      var v6 = this.cols;
      var v10 = this.grid;
      var v5 = new Array();
      var v7;
      var v3 = 0;
      while (v3 < v8) {
        v5[v3] = new Array();
        var v2 = 0;
        while (v2 < v6) {
          var v4 = instr.charCodeAt(cnum);
          v5[v3][v2] = v4;
          ++cnum;
          ++v2;
        }
        ++v3;
      }
      v3 = 0;
      while (v3 < v8) {
        v7 = v10[v3 + 1];
        v2 = 0;
        while (v2 < v6) {
          v7[v2 + 1].SetState(v5[v3][v2] - CHAR_PAD);
          ++v2;
        }
        ++v3;
      }
    };

  }

  frame 1 {
    COL_NONE = 0;
    COL_AXIS = 1;
    COL_OTHER = 2;
  }

  frame 1 {
    function QueryPointvsTileMap(x, y) {
      var v1 = tiles.GetTile_S(x, y);
      return TestPointTile(x, y, v1);
    }

  }

  frame 1 {
    function TestPoint_Full(x, y, t) {
      return true;
    }

  }

  frame 1 {
    function TestPoint_Half(x, y, t) {
      var v3 = t.signx;
      var v2 = t.signy;
      var v5 = x - t.pos.x;
      var v4 = y - t.pos.y;
      if (v5 * v3 + v4 * v2 <= 0) {
        return true;
      } else {
        return false;
      }
    }

  }

  frame 1 {
    function TestPoint_Concave(x, y, t) {
      var v4 = t.pos.x + t.signx * t.xw - x;
      var v3 = t.pos.y + t.signy * t.yw - y;
      var v2 = t.xw * 2;
      if (v2 * v2 <= v4 * v4 + v3 * v3) {
        return true;
      } else {
        return false;
      }
    }

  }

  frame 1 {
    function TestPoint_Convex(x, y, t) {
      var v4 = x - (t.pos.x - t.signx * t.xw);
      var v3 = y - (t.pos.y - t.signy * t.yw);
      var v2 = t.xw * 2;
      if (v4 * v4 + v3 * v3 <= v2 * v2) {
        return true;
      } else {
        return false;
      }
    }

  }

  frame 1 {
    function TestPoint_45Deg(x, y, t) {
      var v3 = x - t.pos.x;
      var v2 = y - t.pos.y;
      if (v3 * t.sx + v2 * t.sy <= 0) {
        return true;
      } else {
        return false;
      }
    }

  }

  frame 1 {
    function TestPoint_22DegS(x, y, t) {
      var v3 = x - (t.pos.x + t.signx * t.xw);
      var v2 = y - (t.pos.y - t.signy * t.yw);
      if (v3 * t.sx + v2 * t.sy <= 0) {
        return true;
      } else {
        return false;
      }
    }

  }

  frame 1 {
    function TestPoint_22DegB(x, y, t) {
      var v3 = x - (t.pos.x - t.signx * t.xw);
      var v2 = y - (t.pos.y + t.signy * t.yw);
      if (v3 * t.sx + v2 * t.sy <= 0) {
        return true;
      } else {
        return false;
      }
    }

  }

  frame 1 {
    function TestPoint_67DegS(x, y, t) {
      var v3 = x - (t.pos.x - t.signx * t.xw);
      var v2 = y - (t.pos.y + t.signy * t.yw);
      if (v3 * t.sx + v2 * t.sy <= 0) {
        return true;
      } else {
        return false;
      }
    }

  }

  frame 1 {
    function TestPoint_67DegB(x, y, t) {
      var v3 = x - (t.pos.x + t.signx * t.xw);
      var v2 = y - (t.pos.y - t.signy * t.yw);
      if (v3 * t.sx + v2 * t.sy <= 0) {
        return true;
      } else {
        return false;
      }
    }

  }

  frame 1 {
    function TestPointTile(x, y, t) {
      if (0 < t.ID) {
        return Test_PointTile[t.CTYPE](x, y, t);
      } else {
        return false;
      }
    }

    Test_PointTile = new Object();
    Test_PointTile[CTYPE_FULL] = TestPoint_Full;
    Test_PointTile[CTYPE_45DEG] = TestPoint_45Deg;
    Test_PointTile[CTYPE_CONCAVE] = TestPoint_Concave;
    Test_PointTile[CTYPE_CONVEX] = TestPoint_Convex;
    Test_PointTile[CTYPE_22DEGs] = TestPoint_22DegS;
    Test_PointTile[CTYPE_22DEGb] = TestPoint_22DegB;
    Test_PointTile[CTYPE_67DEGs] = TestPoint_67DegS;
    Test_PointTile[CTYPE_67DEGb] = TestPoint_67DegB;
    Test_PointTile[CTYPE_HALF] = TestPoint_Half;
  }

  frame 1 {
    function CollideAABBvsTileMap(box) {
      var v4 = box.pos;
      var v1 = tiles.GetTile_V(v4);
      box.cell = v1;
      var v18 = v1.pos.x;
      var v11 = v1.pos.y;
      var v15 = v1.xw;
      var v14 = v1.yw;
      var v9 = v4.x - v18;
      var v8 = v4.y - v11;
      if (0 < v1.ID) {
        var v22 = v15 + box.xw - Math.abs(v9);
        var v20 = v14 + box.yw - Math.abs(v8);
        if (v22 < v20) {
          if (v9 < 0) {
            v22 *= -1;
            v20 = 0;
          } else {
            v20 = 0;
          }
        } else {
          if (v8 < 0) {
            v22 = 0;
            v20 *= -1;
          } else {
            v22 = 0;
          }
        }
        ResolveBoxTile(v22, v20, box, v1);
      }
      var v28 = false;
      var v21 = false;
      v8 = v4.y - v11;
      v20 = Math.abs(v8) + box.yw - v14;
      if (0 < v20) {
        v28 = true;
        var v7;
        var v26;
        var v13;
        var v16;
        if (v8 < 0) {
          v7 = v1.eU;
          v26 = v1.nU;
          v13 = v20;
          v16 = 1;
        } else {
          v7 = v1.eD;
          v26 = v1.nD;
          v13 = -v20;
          v16 = -1;
        }
        if (0 < v7) {
          if (v7 == EID_SOLID) {
            v21 = COL_AXIS;
            box.ReportCollisionVsWorld(0, v13, 0, v16, v26);
          } else {
            v21 = ResolveBoxTile(0, v13, box, v26);
          }
        }
      }
      var v27 = false;
      var v19 = false;
      v9 = v4.x - v18;
      v22 = Math.abs(v9) + box.xw - v15;
      if (0 < v22) {
        v27 = true;
        var v10;
        var v23;
        var v12;
        var v17;
        if (v9 < 0) {
          v10 = v1.eL;
          v23 = v1.nL;
          v12 = v22;
          v17 = 1;
        } else {
          v10 = v1.eR;
          v23 = v1.nR;
          v12 = -v22;
          v17 = -1;
        }
        if (0 < v10) {
          if (v10 == EID_SOLID) {
            v19 = COL_AXIS;
            box.ReportCollisionVsWorld(v12, 0, v17, 0, v23);
          } else {
            v19 = ResolveBoxTile(v12, 0, box, v23);
          }
        }
      }
      if (v27 && v19 != COL_AXIS && v28 && v21 != COL_AXIS) {
        v9 = v4.x - v18;
        v8 = v4.y - v11;
        v22 = Math.abs(v9) + box.xw - v15;
        v20 = Math.abs(v8) + box.yw - v14;
        var v6 = 0;
        var v5 = 0;
        var v30 = false;
        var v3;
        if (v9 < 0 && v8 < 0) {
          v10 = v1.nU.eL;
          v7 = v1.nL.eU;
          v3 = v1.nU.nL;
        } else {
          if (v9 < 0 && 0 < v8) {
            v10 = v1.nD.eL;
            v7 = v1.nL.eD;
            v3 = v1.nD.nL;
          } else {
            if (0 < v9 && 0 < v8) {
              v10 = v1.nD.eR;
              v7 = v1.nR.eD;
              v3 = v1.nD.nR;
            } else {
              if (0 < v9 && v8 < 0) {
                v10 = v1.nU.eR;
                v7 = v1.nR.eU;
                v3 = v1.nU.nR;
              } else {}
            }
          }
        }
        var v25;
        var v24;
        if (v22 < v20) {
          v24 = 0;
          v5 = v24;
          if (v9 < 0) {
            v6 = v22;
            v25 = 1;
          } else {
            v6 = -v22;
            v25 = -1;
          }
        } else {
          v25 = 0;
          v6 = v25;
          if (v8 < 0) {
            v5 = v20;
            v24 = 1;
          } else {
            v5 = -v20;
            v24 = -1;
          }
        }
        if (0 < v10) {
          if (0 < v7) {
            if (v10 == EID_SOLID) {
              if (v7 == EID_SOLID) {
                box.ReportCollisionVsWorld(v6, v5, v25, v24, v3);
              } else {
                var v29 = ResolveBoxTile(v6, v5, box, v3);
                if (v29 == COL_NONE) {
                  box.ReportCollisionVsWorld(v12, 0, v17, 0, v3);
                }
              }
            } else {
              if (v7 == EID_SOLID) {
                var v29 = ResolveBoxTile(v6, v5, box, v3);
                if (v29 == COL_NONE) {
                  box.ReportCollisionVsWorld(0, v13, 0, v16, v3);
                }
              } else {
                ResolveBoxTile(v6, v5, box, v3);
              }
            }
          } else {
            if (v10 == EID_SOLID) {
              box.ReportCollisionVsWorld(v12, 0, v17, 0, v3);
            } else {
              ResolveBoxTile(v6, v5, box, v3);
            }
          }
        } else {
          if (0 < v7) {
            if (v7 == EID_SOLID) {
              box.ReportCollisionVsWorld(0, v13, 0, v16, v3);
            } else {
              ResolveBoxTile(v6, v5, box, v3);
            }
          } else {}
        }
      }
    }

  }

  frame 1 {
    function ProjAABB_Full(x, y, obj, t) {
      var v1 = Math.sqrt(x * x + y * y);
      obj.ReportCollisionVsWorld(x, y, x / v1, y / v1, t);
      return COL_AXIS;
    }

  }

  frame 1 {
    function ProjAABB_Half(x, y, obj, t) {
      var v3 = t.signx;
      var v2 = t.signy;
      var v10 = obj.pos.x - v3 * obj.xw - t.pos.x;
      var v9 = obj.pos.y - v2 * obj.yw - t.pos.y;
      var v6 = v10 * v3 + v9 * v2;
      if (v6 < 0) {
        v3 *= -v6;
        v2 *= -v6;
        var v11 = Math.sqrt(v3 * v3 + v2 * v2);
        var v5 = Math.sqrt(x * x + y * y);
        if (v5 < v11) {
          obj.ReportCollisionVsWorld(x, y, x / v5, y / v5, t);
          return COL_AXIS;
          return COL_NONE;
        }
        obj.ReportCollisionVsWorld(v3, v2, t.signx, t.signy, t);
        return COL_OTHER;
      }
      return COL_NONE;
    }

  }

  frame 1 {
    function ProjAABB_Concave(x, y, obj, t) {
      var v12 = t.signx;
      var v11 = t.signy;
      var v3 = t.pos.x + v12 * t.xw - (obj.pos.x - v12 * obj.xw);
      var v2 = t.pos.y + v11 * t.yw - (obj.pos.y - v11 * obj.yw);
      var v8 = t.xw * 2;
      var v13 = Math.sqrt(v8 * v8 + 0);
      var v6 = Math.sqrt(v3 * v3 + v2 * v2);
      var v4 = v6 - v13;
      if (0 < v4) {
        var v7 = Math.sqrt(x * x + y * y);
        if (v7 < v4) {
          obj.ReportCollisionVsWorld(x, y, x / v7, y / v7, t);
          return COL_AXIS;
          return COL_NONE;
        }
        v3 /= v6;
        v2 /= v6;
        obj.ReportCollisionVsWorld(v3 * v4, v2 * v4, v3, v2, t);
        return COL_OTHER;
      }
      return COL_NONE;
    }

  }

  frame 1 {
    function ProjAABB_Convex(x, y, obj, t) {
      var v8 = t.signx;
      var v7 = t.signy;
      var v3 = obj.pos.x - v8 * obj.xw - (t.pos.x - v8 * t.xw);
      var v2 = obj.pos.y - v7 * obj.yw - (t.pos.y - v7 * t.yw);
      var v5 = Math.sqrt(v3 * v3 + v2 * v2);
      var v9 = t.xw * 2;
      var v13 = Math.sqrt(v9 * v9 + 0);
      var v6 = v13 - v5;
      if (v8 * v3 < 0 || v7 * v2 < 0) {
        var v10 = Math.sqrt(x * x + y * y);
        obj.ReportCollisionVsWorld(x, y, x / v10, y / v10, t);
        return COL_AXIS;
        return COL_NONE;
      }
      if (0 < v6) {
        v3 /= v5;
        v2 /= v5;
        obj.ReportCollisionVsWorld(v3 * v6, v2 * v6, v3, v2, t);
        return COL_OTHER;
      }
      return COL_NONE;
    }

  }

  frame 1 {
    function ProjAABB_45Deg(x, y, obj, t) {
      var v13 = t.signx;
      var v12 = t.signy;
      var v10 = obj.pos.x - v13 * obj.xw - t.pos.x;
      var v9 = obj.pos.y - v12 * obj.yw - t.pos.y;
      var v3 = t.sx;
      var v2 = t.sy;
      var v6 = v10 * v3 + v9 * v2;
      if (v6 < 0) {
        v3 *= -v6;
        v2 *= -v6;
        var v11 = Math.sqrt(v3 * v3 + v2 * v2);
        var v5 = Math.sqrt(x * x + y * y);
        if (v5 < v11) {
          obj.ReportCollisionVsWorld(x, y, x / v5, y / v5, t);
          return COL_AXIS;
          return COL_NONE;
        }
        obj.ReportCollisionVsWorld(v3, v2, t.sx, t.sy);
        return COL_OTHER;
      }
      return COL_NONE;
    }

  }

  frame 1 {
    function ProjAABB_22DegS(x, y, obj, t) {
      var v13 = t.signx;
      var v8 = t.signy;
      var v14 = obj.pos.y - v8 * obj.yw;
      var v3 = t.pos.y - v14;
      if (0 < v3 * v8) {
        var v16 = obj.pos.x - v13 * obj.xw - (t.pos.x + v13 * t.xw);
        var v15 = obj.pos.y - v8 * obj.yw - (t.pos.y - v8 * t.yw);
        var v5 = t.sx;
        var v4 = t.sy;
        var v9 = v16 * v5 + v15 * v4;
        if (v9 < 0) {
          v5 *= -v9;
          v4 *= -v9;
          var v10 = Math.sqrt(v5 * v5 + v4 * v4);
          var v7 = Math.sqrt(x * x + y * y);
          var v6 = Math.abs(v3);
          if (v7 < v10) {
            if (v6 < v7) {
              obj.ReportCollisionVsWorld(0, v3, 0, v3 / v6, t);
              return COL_OTHER;
            } else {
              obj.ReportCollisionVsWorld(x, y, x / v7, y / v7, t);
              return COL_AXIS;
            }
            return COL_NONE;
          }
          if (v6 < v10) {
            obj.ReportCollisionVsWorld(0, v3, 0, v3 / v6, t);
            return COL_OTHER;
            return COL_NONE;
          }
          obj.ReportCollisionVsWorld(v5, v4, t.sx, t.sy, t);
          return COL_OTHER;
        }
      }
      return COL_NONE;
    }

  }

  frame 1 {
    function ProjAABB_22DegB(x, y, obj, t) {
      var v10 = t.signx;
      var v9 = t.signy;
      var v12 = obj.pos.x - v10 * obj.xw - (t.pos.x - v10 * t.xw);
      var v11 = obj.pos.y - v9 * obj.yw - (t.pos.y + v9 * t.yw);
      var v3 = t.sx;
      var v2 = t.sy;
      var v6 = v12 * v3 + v11 * v2;
      if (v6 < 0) {
        v3 *= -v6;
        v2 *= -v6;
        var v13 = Math.sqrt(v3 * v3 + v2 * v2);
        var v5 = Math.sqrt(x * x + y * y);
        if (v5 < v13) {
          obj.ReportCollisionVsWorld(x, y, x / v5, y / v5, t);
          return COL_AXIS;
          return COL_NONE;
        }
        obj.ReportCollisionVsWorld(v3, v2, t.sx, t.sy, t);
        return COL_OTHER;
      }
      return COL_NONE;
    }

  }

  frame 1 {
    function ProjAABB_67DegS(x, y, obj, t) {
      var v8 = t.signx;
      var v13 = t.signy;
      var v14 = obj.pos.x - v8 * obj.xw;
      var v3 = t.pos.x - v14;
      if (0 < v3 * v8) {
        var v16 = obj.pos.x - v8 * obj.xw - (t.pos.x - v8 * t.xw);
        var v15 = obj.pos.y - v13 * obj.yw - (t.pos.y + v13 * t.yw);
        var v5 = t.sx;
        var v4 = t.sy;
        var v9 = v16 * v5 + v15 * v4;
        if (v9 < 0) {
          v5 *= -v9;
          v4 *= -v9;
          var v10 = Math.sqrt(v5 * v5 + v4 * v4);
          var v7 = Math.sqrt(x * x + y * y);
          var v6 = Math.abs(v3);
          if (v7 < v10) {
            if (v6 < v7) {
              obj.ReportCollisionVsWorld(v3, 0, v3 / v6, 0, t);
              return COL_OTHER;
            } else {
              obj.ReportCollisionVsWorld(x, y, x / v7, y / v7, t);
              return COL_AXIS;
            }
            return COL_NONE;
          }
          if (v6 < v10) {
            obj.ReportCollisionVsWorld(v3, 0, v3 / v6, 0, t);
            return COL_OTHER;
            return COL_NONE;
          }
          obj.ReportCollisionVsWorld(v5, v4, t.sx, t.sy, t);
          return COL_OTHER;
        }
      }
      return COL_NONE;
    }

  }

  frame 1 {
    function ProjAABB_67DegB(x, y, obj, t) {
      var v10 = t.signx;
      var v9 = t.signy;
      var v12 = obj.pos.x - v10 * obj.xw - (t.pos.x + v10 * t.xw);
      var v11 = obj.pos.y - v9 * obj.yw - (t.pos.y - v9 * t.yw);
      var v3 = t.sx;
      var v2 = t.sy;
      var v6 = v12 * v3 + v11 * v2;
      if (v6 < 0) {
        v3 *= -v6;
        v2 *= -v6;
        var v13 = Math.sqrt(v3 * v3 + v2 * v2);
        var v5 = Math.sqrt(x * x + y * y);
        if (v5 < v13) {
          obj.ReportCollisionVsWorld(x, y, x / v5, y / v5, t);
          return COL_AXIS;
          return COL_NONE;
        }
        obj.ReportCollisionVsWorld(v3, v2, t.sx, t.sy, t);
        return COL_OTHER;
      }
      return COL_NONE;
    }

  }

  frame 1 {
    function ResolveBoxTile(x, y, box, t) {
      if (0 < t.ID) {
        return Proj_AABBTile[t.CTYPE](x, y, box, t);
      } else {
        return false;
      }
    }

    Proj_AABBTile = new Object();
    Proj_AABBTile[CTYPE_FULL] = ProjAABB_Full;
    Proj_AABBTile[CTYPE_45DEG] = ProjAABB_45Deg;
    Proj_AABBTile[CTYPE_CONCAVE] = ProjAABB_Concave;
    Proj_AABBTile[CTYPE_CONVEX] = ProjAABB_Convex;
    Proj_AABBTile[CTYPE_22DEGs] = ProjAABB_22DegS;
    Proj_AABBTile[CTYPE_22DEGb] = ProjAABB_22DegB;
    Proj_AABBTile[CTYPE_67DEGs] = ProjAABB_67DegS;
    Proj_AABBTile[CTYPE_67DEGb] = ProjAABB_67DegB;
    Proj_AABBTile[CTYPE_HALF] = ProjAABB_Half;
  }

  frame 1 {
    function CollideCirclevsTileMap(obj) {
      var v8 = obj.pos;
      var v11 = obj.r;
      var v1 = tiles.GetTile_V(v8);
      var v21 = v1.pos.x;
      var v20 = v1.pos.y;
      var v23 = v1.xw;
      var v22 = v1.yw;
      var v7 = v8.x - v21;
      var v6 = v8.y - v20;
      if (0 < v1.ID) {
        var v13 = v23 + v11 - Math.abs(v7);
        var v12 = v22 + v11 - Math.abs(v6);
        ResolveCircleTile(v13, v12, 0, 0, obj, v1);
      }
      var v25 = false;
      var v17 = false;
      v6 = v8.y - v20;
      v12 = Math.abs(v6) + v11 - v22;
      if (0 < v12) {
        v25 = true;
        var v5;
        var v19;
        var v10;
        if (v6 < 0) {
          v5 = v1.eU;
          v19 = v1.nU;
          v10 = 1;
        } else {
          v5 = v1.eD;
          v19 = v1.nD;
          v10 = -1;
        }
        if (0 < v5) {
          if (v5 == EID_SOLID) {
            v17 = COL_AXIS;
            obj.ReportCollisionVsWorld(0, v12 * v10, 0, v10, v19);
          } else {
            v17 = ResolveCircleTile(0, v12, 0, v10, obj, v19);
          }
        }
      }
      var v24 = false;
      var v15 = false;
      v7 = v8.x - v21;
      v13 = Math.abs(v7) + v11 - v23;
      if (0 < v13) {
        v24 = true;
        var v4;
        var v18;
        var v9;
        if (v7 < 0) {
          v4 = v1.eL;
          v18 = v1.nL;
          v9 = 1;
        } else {
          v4 = v1.eR;
          v18 = v1.nR;
          v9 = -1;
        }
        if (0 < v4) {
          if (v4 == EID_SOLID) {
            v15 = COL_AXIS;
            obj.ReportCollisionVsWorld(v13 * v9, 0, v9, 0, v18);
          } else {
            v15 = ResolveCircleTile(v13, 0, v9, 0, obj, v18);
          }
        }
      }
      if (v24 && v15 != COL_AXIS && v25 && v17 != COL_AXIS) {
        var v2;
        var v28 = false;
        if (v7 < 0 && v6 < 0) {
          v4 = v1.nU.eL;
          v5 = v1.nL.eU;
          v2 = v1.nU.nL;
        } else {
          if (v7 < 0 && 0 < v6) {
            v4 = v1.nD.eL;
            v5 = v1.nL.eD;
            v2 = v1.nD.nL;
          } else {
            if (0 < v7 && 0 < v6) {
              v4 = v1.nD.eR;
              v5 = v1.nR.eD;
              v2 = v1.nD.nR;
            } else {
              if (0 < v7 && v6 < 0) {
                v4 = v1.nU.eR;
                v5 = v1.nR.eU;
                v2 = v1.nU.nR;
              } else {}
            }
          }
        }
        if (0 < v4 + v5) {
          if (v4 == EID_SOLID || v5 == EID_SOLID) {
            var v27 = v2.pos.x + v9 * v2.xw;
            var v26 = v2.pos.y + v10 * v2.yw;
            v7 = obj.pos.x - v27;
            v6 = obj.pos.y - v26;
            var v14 = Math.sqrt(v7 * v7 + v6 * v6);
            var v16 = obj.r - v14;
            if (0 < v16) {
              if (v14 == 0) {
                v7 = v9 / Math.SQRT2;
                v6 = v10 / Math.SQRT2;
              } else {
                v7 /= v14;
                v6 /= v14;
              }
              obj.ReportCollisionVsWorld(v7 * v16, v6 * v16, v7, v6, v2);
            }
          } else {
            v7 = v8.x - v2.pos.x;
            v6 = v8.y - v2.pos.y;
            v13 = Math.abs(v7) + v11 - v2.xw;
            v12 = Math.abs(v6) + v11 - v2.yw;
            ResolveCircleTile(v13, v12, v9, v10, obj, v2);
          }
        } else {}
      }
    }

  }

  frame 1 {
    function ProjCircle_Full(x, y, oH, oV, obj, t) {
      if (oH == 0) {
        if (oV == 0) {
          if (x < y) {
            var v4 = obj.pos.x - t.pos.x;
            if (v4 < 0) {
              obj.ReportCollisionVsWorld(-x, 0, -1, 0, t);
              return COL_AXIS;
            } else {
              obj.ReportCollisionVsWorld(x, 0, 1, 0, t);
              return COL_AXIS;
            }
          } else {
            var v3 = obj.pos.y - t.pos.y;
            if (v3 < 0) {
              obj.ReportCollisionVsWorld(0, -y, 0, -1, t);
              return COL_AXIS;
            } else {
              obj.ReportCollisionVsWorld(0, y, 0, 1, t);
              return COL_AXIS;
            }
          }
        } else {
          static_rend.DrawCrossR(t.pos, t.xw);
          obj.ReportCollisionVsWorld(0, y * oV, 0, oV, t);
          return COL_AXIS;
        }
        return COL_NONE;
      }
      if (oV == 0) {
        static_rend.DrawCrossR(t.pos, t.xw);
        obj.ReportCollisionVsWorld(x * oH, 0, oH, 0, t);
        return COL_AXIS;
        return COL_NONE;
      }
      static_rend.DrawCrossR(t.pos, t.xw);
      var v12 = t.pos.x + oH * t.xw;
      var v11 = t.pos.y + oV * t.yw;
      var v4 = obj.pos.x - v12;
      var v3 = obj.pos.y - v11;
      var v5 = Math.sqrt(v4 * v4 + v3 * v3);
      var v7 = obj.r - v5;
      if (0 < v7) {
        if (v5 == 0) {
          v4 = oH / Math.SQRT2;
          v3 = oV / Math.SQRT2;
        } else {
          v4 /= v5;
          v3 /= v5;
        }
        obj.ReportCollisionVsWorld(v4 * v7, v3 * v7, v4, v3, t);
        return COL_OTHER;
      }
      return COL_NONE;
    }

  }

  frame 1 {
    function ProjCircle_Half(x, y, oH, oV, obj, t) {
      var v7 = t.signx;
      var v13 = t.signy;
      var v17 = oH * v7 + oV * v13;
      if (0 < v17) {
        return COL_NONE;
        return COL_NONE;
      }
      if (oH == 0) {
        if (oV == 0) {
          var v23 = obj.r;
          var v21 = obj.pos.x - v7 * v23 - t.pos.x;
          var v20 = obj.pos.y - v13 * v23 - t.pos.y;
          var v9 = v7;
          var v8 = v13;
          var v16 = v21 * v9 + v20 * v8;
          if (v16 < 0) {
            v9 *= -v16;
            v8 *= -v16;
            var v22 = Math.sqrt(v9 * v9 + v8 * v8);
            var v15 = Math.sqrt(x * x + y * y);
            if (v15 < v22) {
              obj.ReportCollisionVsWorld(x, y, x / v15, y / v15, t);
              return COL_AXIS;
            } else {
              obj.ReportCollisionVsWorld(v9, v8, t.signx, t.signy);
              return COL_OTHER;
            }
            return true;
          }
        } else {
          if (v17 == 0) {
            var v23 = obj.r;
            var v6 = obj.pos.x - t.pos.x;
            if (v6 * v7 < 0) {
              obj.ReportCollisionVsWorld(0, y * oV, 0, oV, t);
              return COL_AXIS;
            } else {
              var v5 = obj.pos.y - (t.pos.y + oV * t.yw);
              var v10 = Math.sqrt(v6 * v6 + v5 * v5);
              var v14 = obj.r - v10;
              if (0 < v14) {
                if (v10 == 0) {
                  v6 = v7 / Math.SQRT2;
                  v5 = oV / Math.SQRT2;
                } else {
                  v6 /= v10;
                  v5 /= v10;
                }
                obj.ReportCollisionVsWorld(v6 * v14, v5 * v14, v6, v5, t);
                return COL_OTHER;
              }
            }
          } else {
            obj.ReportCollisionVsWorld(0, y * oV, 0, oV, t);
            return COL_AXIS;
          }
        }
        return COL_NONE;
      }
      if (oV == 0) {
        if (v17 == 0) {
          var v23 = obj.r;
          var v5 = obj.pos.y - t.pos.y;
          if (v5 * v13 < 0) {
            obj.ReportCollisionVsWorld(x * oH, 0, oH, 0, t);
            return COL_AXIS;
          } else {
            var v6 = obj.pos.x - (t.pos.x + oH * t.xw);
            var v10 = Math.sqrt(v6 * v6 + v5 * v5);
            var v14 = obj.r - v10;
            if (0 < v14) {
              if (v10 == 0) {
                v6 = v7 / Math.SQRT2;
                v5 = oV / Math.SQRT2;
              } else {
                v6 /= v10;
                v5 /= v10;
              }
              obj.ReportCollisionVsWorld(v6 * v14, v5 * v14, v6, v5, t);
              return COL_OTHER;
            }
          }
        } else {
          obj.ReportCollisionVsWorld(x * oH, 0, oH, 0, t);
          return COL_AXIS;
        }
        return COL_NONE;
      }
      var v19 = t.pos.x + oH * t.xw;
      var v18 = t.pos.y + oV * t.yw;
      var v6 = obj.pos.x - v19;
      var v5 = obj.pos.y - v18;
      var v10 = Math.sqrt(v6 * v6 + v5 * v5);
      var v14 = obj.r - v10;
      if (0 < v14) {
        if (v10 == 0) {
          v6 = oH / Math.SQRT2;
          v5 = oV / Math.SQRT2;
        } else {
          v6 /= v10;
          v5 /= v10;
        }
        obj.ReportCollisionVsWorld(v6 * v14, v5 * v14, v6, v5, t);
        return COL_OTHER;
      }
      return COL_NONE;
    }

  }

  frame 1 {
    function ProjCircle_45Deg(x, y, oH, oV, obj, t) {
      var v12 = t.signx;
      var v11 = t.signy;
      if (oH == 0) {
        if (oV == 0) {
          var v15 = t.sx;
          var v14 = t.sy;
          var v4 = obj.pos.x - v15 * obj.r - t.pos.x;
          var v3 = obj.pos.y - v14 * obj.r - t.pos.y;
          var v21 = v4 * v15 + v3 * v14;
          if (v21 < 0) {
            v15 *= -v21;
            v14 *= -v21;
            if (x < y) {
              lenP = x;
              y = 0;
              if (obj.pos.x - t.pos.x < 0) {
                x *= -1;
              }
            } else {
              lenP = y;
              x = 0;
              if (obj.pos.y - t.pos.y < 0) {
                y *= -1;
              }
            }
            var v20 = Math.sqrt(v15 * v15 + v14 * v14);
            if (lenP < v20) {
              obj.ReportCollisionVsWorld(x, y, x / lenP, y / lenP, t);
              return COL_AXIS;
            } else {
              obj.ReportCollisionVsWorld(v15, v14, t.sx, t.sy, t);
              return COL_OTHER;
            }
          }
        } else {
          if (v11 * oV < 0) {
            obj.ReportCollisionVsWorld(0, y * oV, 0, oV, t);
            return COL_AXIS;
          } else {
            var v15 = t.sx;
            var v14 = t.sy;
            var v4 = obj.pos.x - (t.pos.x - v12 * t.xw);
            var v3 = obj.pos.y - (t.pos.y + oV * t.yw);
            var v17 = v4 * -v14 + v3 * v15;
            if (0 < v17 * v12 * v11) {
              var v13 = Math.sqrt(v4 * v4 + v3 * v3);
              var v16 = obj.r - v13;
              if (0 < v16) {
                v4 /= v13;
                v3 /= v13;
                obj.ReportCollisionVsWorld(v4 * v16, v3 * v16, v4, v3, t);
                return COL_OTHER;
              }
            } else {
              var v21 = v4 * v15 + v3 * v14;
              var v16 = obj.r - Math.abs(v21);
              if (0 < v16) {
                obj.ReportCollisionVsWorld(v15 * v16, v14 * v16, v15, v14, t);
                return COL_OTHER;
              }
            }
          }
        }
        return COL_NONE;
      }
      if (oV == 0) {
        if (v12 * oH < 0) {
          obj.ReportCollisionVsWorld(x * oH, 0, oH, 0, t);
          return COL_AXIS;
        } else {
          v15 = t.sx;
          v14 = t.sy;
          v4 = obj.pos.x - (t.pos.x + oH * t.xw);
          v3 = obj.pos.y - (t.pos.y - v11 * t.yw);
          v17 = v4 * -v14 + v3 * v15;
          if (v17 * v12 * v11 < 0) {
            var v13 = Math.sqrt(v4 * v4 + v3 * v3);
            v16 = obj.r - v13;
            if (0 < v16) {
              v4 /= v13;
              v3 /= v13;
              obj.ReportCollisionVsWorld(v4 * v16, v3 * v16, v4, v3, t);
              return COL_OTHER;
            }
          } else {
            v21 = v4 * v15 + v3 * v14;
            v16 = obj.r - Math.abs(v21);
            if (0 < v16) {
              obj.ReportCollisionVsWorld(v15 * v16, v14 * v16, v15, v14, t);
              return COL_OTHER;
            }
          }
        }
        return COL_NONE;
      }
      if (0 < v12 * oH + v11 * oV) {
        return COL_NONE;
        return COL_NONE;
      }
      var v19 = t.pos.x + oH * t.xw;
      var v18 = t.pos.y + oV * t.yw;
      var v7 = obj.pos.x - v19;
      var v6 = obj.pos.y - v18;
      var v13 = Math.sqrt(v7 * v7 + v6 * v6);
      v16 = obj.r - v13;
      if (0 < v16) {
        if (v13 == 0) {
          v7 = oH / Math.SQRT2;
          v6 = oV / Math.SQRT2;
        } else {
          v7 /= v13;
          v6 /= v13;
        }
        obj.ReportCollisionVsWorld(v7 * v16, v6 * v16, v7, v6, t);
        return COL_OTHER;
      }
      return COL_NONE;
    }

  }

  frame 1 {
    function ProjCircle_Concave(x, y, oH, oV, obj, t) {
      var v13 = t.signx;
      var v12 = t.signy;
      if (oH == 0) {
        if (oV == 0) {
          var v8 = t.pos.x + v13 * t.xw - obj.pos.x;
          var v7 = t.pos.y + v12 * t.yw - obj.pos.y;
          var v15 = t.xw * 2;
          var v18 = Math.sqrt(v15 * v15 + 0);
          var v11 = Math.sqrt(v8 * v8 + v7 * v7);
          var v14 = v11 + obj.r - v18;
          if (0 < v14) {
            if (x < y) {
              lenP = x;
              y = 0;
              if (obj.pos.x - t.pos.x < 0) {
                x *= -1;
              }
            } else {
              lenP = y;
              x = 0;
              if (obj.pos.y - t.pos.y < 0) {
                y *= -1;
              }
            }
            if (lenP < v14) {
              obj.ReportCollisionVsWorld(x, y, x / lenP, y / lenP, t);
              return COL_AXIS;
            } else {
              v8 /= v11;
              v7 /= v11;
              obj.ReportCollisionVsWorld(v8 * v14, v7 * v14, v8, v7, t);
              return COL_OTHER;
            }
          } else {
            return COL_NONE;
          }
        } else {
          if (v12 * oV < 0) {
            obj.ReportCollisionVsWorld(0, y * oV, 0, oV, t);
            return COL_AXIS;
          } else {
            var v17 = t.pos.x - v13 * t.xw;
            var v16 = t.pos.y + oV * t.yw;
            var v6 = obj.pos.x - v17;
            var v5 = obj.pos.y - v16;
            var v11 = Math.sqrt(v6 * v6 + v5 * v5);
            var v14 = obj.r - v11;
            if (0 < v14) {
              if (v11 == 0) {
                v6 = 0;
                v5 = oV;
              } else {
                v6 /= v11;
                v5 /= v11;
              }
              obj.ReportCollisionVsWorld(v6 * v14, v5 * v14, v6, v5, t);
              return COL_OTHER;
            }
          }
        }
        return COL_NONE;
      }
      if (oV == 0) {
        if (v13 * oH < 0) {
          obj.ReportCollisionVsWorld(x * oH, 0, oH, 0, t);
          return COL_AXIS;
        } else {
          v17 = t.pos.x + oH * t.xw;
          v16 = t.pos.y - v12 * t.yw;
          v6 = obj.pos.x - v17;
          v5 = obj.pos.y - v16;
          v11 = Math.sqrt(v6 * v6 + v5 * v5);
          v14 = obj.r - v11;
          if (0 < v14) {
            if (v11 == 0) {
              v6 = oH;
              v5 = 0;
            } else {
              v6 /= v11;
              v5 /= v11;
            }
            obj.ReportCollisionVsWorld(v6 * v14, v5 * v14, v6, v5, t);
            return COL_OTHER;
          }
        }
        return COL_NONE;
      }
      if (0 < v13 * oH + v12 * oV) {
        return COL_NONE;
        return COL_NONE;
      }
      v17 = t.pos.x + oH * t.xw;
      v16 = t.pos.y + oV * t.yw;
      v6 = obj.pos.x - v17;
      v5 = obj.pos.y - v16;
      v11 = Math.sqrt(v6 * v6 + v5 * v5);
      v14 = obj.r - v11;
      if (0 < v14) {
        if (v11 == 0) {
          v6 = oH / Math.SQRT2;
          v5 = oV / Math.SQRT2;
        } else {
          v6 /= v11;
          v5 /= v11;
        }
        obj.ReportCollisionVsWorld(v6 * v14, v5 * v14, v6, v5, t);
        return COL_OTHER;
      }
      return COL_NONE;
    }

  }

  frame 1 {
    function ProjCircle_Convex(x, y, oH, oV, obj, t) {
      var v7 = t.signx;
      var v6 = t.signy;
      if (oH == 0) {
        if (oV == 0) {
          var v9 = obj.pos.x - (t.pos.x - v7 * t.xw);
          var v8 = obj.pos.y - (t.pos.y - v6 * t.yw);
          var v15 = t.xw * 2;
          var v18 = Math.sqrt(v15 * v15 + 0);
          var v13 = Math.sqrt(v9 * v9 + v8 * v8);
          var v14 = v18 + obj.r - v13;
          if (0 < v14) {
            if (x < y) {
              lenP = x;
              y = 0;
              if (obj.pos.x - t.pos.x < 0) {
                x *= -1;
              }
            } else {
              lenP = y;
              x = 0;
              if (obj.pos.y - t.pos.y < 0) {
                y *= -1;
              }
            }
            if (lenP < v14) {
              obj.ReportCollisionVsWorld(x, y, x / lenP, y / lenP, t);
              return COL_AXIS;
            } else {
              v9 /= v13;
              v8 /= v13;
              obj.ReportCollisionVsWorld(v9 * v14, v8 * v14, v9, v8, t);
              return COL_OTHER;
            }
          }
        } else {
          if (v6 * oV < 0) {
            obj.ReportCollisionVsWorld(0, y * oV, 0, oV, t);
            return COL_AXIS;
          } else {
            var v9 = obj.pos.x - (t.pos.x - v7 * t.xw);
            var v8 = obj.pos.y - (t.pos.y - v6 * t.yw);
            var v15 = t.xw * 2;
            var v18 = Math.sqrt(v15 * v15 + 0);
            var v13 = Math.sqrt(v9 * v9 + v8 * v8);
            var v14 = v18 + obj.r - v13;
            if (0 < v14) {
              v9 /= v13;
              v8 /= v13;
              obj.ReportCollisionVsWorld(v9 * v14, v8 * v14, v9, v8, t);
              return COL_OTHER;
            }
          }
        }
        return COL_NONE;
      }
      if (oV == 0) {
        if (v7 * oH < 0) {
          obj.ReportCollisionVsWorld(x * oH, 0, oH, 0, t);
          return COL_AXIS;
        } else {
          v9 = obj.pos.x - (t.pos.x - v7 * t.xw);
          v8 = obj.pos.y - (t.pos.y - v6 * t.yw);
          v15 = t.xw * 2;
          v18 = Math.sqrt(v15 * v15 + 0);
          v13 = Math.sqrt(v9 * v9 + v8 * v8);
          v14 = v18 + obj.r - v13;
          if (0 < v14) {
            v9 /= v13;
            v8 /= v13;
            obj.ReportCollisionVsWorld(v9 * v14, v8 * v14, v9, v8, t);
            return COL_OTHER;
          }
        }
        return COL_NONE;
      }
      if (0 < v7 * oH + v6 * oV) {
        v9 = obj.pos.x - (t.pos.x - v7 * t.xw);
        v8 = obj.pos.y - (t.pos.y - v6 * t.yw);
        v15 = t.xw * 2;
        v18 = Math.sqrt(v15 * v15 + 0);
        v13 = Math.sqrt(v9 * v9 + v8 * v8);
        v14 = v18 + obj.r - v13;
        if (0 < v14) {
          v9 /= v13;
          v8 /= v13;
          obj.ReportCollisionVsWorld(v9 * v14, v8 * v14, v9, v8, t);
          return COL_OTHER;
        }
        return COL_NONE;
      }
      var v17 = t.pos.x + oH * t.xw;
      var v16 = t.pos.y + oV * t.yw;
      var v4 = obj.pos.x - v17;
      var v3 = obj.pos.y - v16;
      v13 = Math.sqrt(v4 * v4 + v3 * v3);
      v14 = obj.r - v13;
      if (0 < v14) {
        if (v13 == 0) {
          v4 = oH / Math.SQRT2;
          v3 = oV / Math.SQRT2;
        } else {
          v4 /= v13;
          v3 /= v13;
        }
        obj.ReportCollisionVsWorld(v4 * v14, v3 * v14, v4, v3, t);
        return COL_OTHER;
      }
      return COL_NONE;
    }

  }

  frame 1 {
    function ProjCircle_22DegS(x, y, oH, oV, obj, t) {
      var v12 = t.signx;
      var v11 = t.signy;
      if (0 < v11 * oV) {
        return COL_NONE;
        return COL_NONE;
      }
      if (oH == 0) {
        if (oV == 0) {
          var v15 = t.sx;
          var v14 = t.sy;
          var v16 = obj.r;
          var v4 = obj.pos.x - (t.pos.x - v12 * t.xw);
          var v3 = obj.pos.y - t.pos.y;
          var v18 = v4 * -v14 + v3 * v15;
          if (0 < v18 * v12 * v11) {
            var v13 = Math.sqrt(v4 * v4 + v3 * v3);
            var v17 = v16 - v13;
            if (0 < v17) {
              v4 /= v13;
              v3 /= v13;
              obj.ReportCollisionVsWorld(v4 * v17, v3 * v17, v4, v3, t);
              return COL_OTHER;
            }
          } else {
            v4 -= v16 * v15;
            v3 -= v16 * v14;
            var v22 = v4 * v15 + v3 * v14;
            if (v22 < 0) {
              v15 *= -v22;
              v14 *= -v22;
              var v21 = Math.sqrt(v15 * v15 + v14 * v14);
              if (x < y) {
                lenP = x;
                y = 0;
                if (obj.pos.x - t.pos.x < 0) {
                  x *= -1;
                }
              } else {
                lenP = y;
                x = 0;
                if (obj.pos.y - t.pos.y < 0) {
                  y *= -1;
                }
              }
              if (lenP < v21) {
                obj.ReportCollisionVsWorld(x, y, x / lenP, y / lenP, t);
                return COL_AXIS;
              } else {
                obj.ReportCollisionVsWorld(v15, v14, t.sx, t.sy, t);
                return COL_OTHER;
              }
            }
          }
        } else {
          obj.ReportCollisionVsWorld(0, y * oV, 0, oV, t);
          return COL_AXIS;
        }
        return COL_NONE;
      }
      if (oV == 0) {
        if (v12 * oH < 0) {
          var v20 = t.pos.x - v12 * t.xw;
          var v19 = t.pos.y;
          var v6 = obj.pos.x - v20;
          var v5 = obj.pos.y - v19;
          if (v5 * v11 < 0) {
            obj.ReportCollisionVsWorld(x * oH, 0, oH, 0, t);
            return COL_AXIS;
          } else {
            var v13 = Math.sqrt(v6 * v6 + v5 * v5);
            var v17 = obj.r - v13;
            if (0 < v17) {
              if (v13 == 0) {
                v6 = oH / Math.SQRT2;
                v5 = oV / Math.SQRT2;
              } else {
                v6 /= v13;
                v5 /= v13;
              }
              obj.ReportCollisionVsWorld(v6 * v17, v5 * v17, v6, v5, t);
              return COL_OTHER;
            }
          }
        } else {
          var v15 = t.sx;
          var v14 = t.sy;
          var v4 = obj.pos.x - (t.pos.x + oH * t.xw);
          var v3 = obj.pos.y - (t.pos.y - v11 * t.yw);
          var v18 = v4 * -v14 + v3 * v15;
          if (v18 * v12 * v11 < 0) {
            var v13 = Math.sqrt(v4 * v4 + v3 * v3);
            var v17 = obj.r - v13;
            if (0 < v17) {
              v4 /= v13;
              v3 /= v13;
              obj.ReportCollisionVsWorld(v4 * v17, v3 * v17, v4, v3, t);
              return COL_OTHER;
            }
          } else {
            var v22 = v4 * v15 + v3 * v14;
            var v17 = obj.r - Math.abs(v22);
            if (0 < v17) {
              obj.ReportCollisionVsWorld(v15 * v17, v14 * v17, v15, v14, t);
              return COL_OTHER;
            }
          }
        }
        return COL_NONE;
      }
      var v20 = t.pos.x + oH * t.xw;
      var v19 = t.pos.y + oV * t.yw;
      var v6 = obj.pos.x - v20;
      var v5 = obj.pos.y - v19;
      var v13 = Math.sqrt(v6 * v6 + v5 * v5);
      v17 = obj.r - v13;
      if (0 < v17) {
        if (v13 == 0) {
          v6 = oH / Math.SQRT2;
          v5 = oV / Math.SQRT2;
        } else {
          v6 /= v13;
          v5 /= v13;
        }
        obj.ReportCollisionVsWorld(v6 * v17, v5 * v17, v6, v5, t);
        return COL_OTHER;
      }
      return COL_NONE;
    }

  }

  frame 1 {
    function ProjCircle_22DegB(x, y, oH, oV, obj, t) {
      var v4 = t.signx;
      var v3 = t.signy;
      if (oH == 0) {
        if (oV == 0) {
          var v13 = t.sx;
          var v12 = t.sy;
          var v16 = obj.r;
          var v22 = obj.pos.x - v13 * v16 - (t.pos.x - v4 * t.xw);
          var v21 = obj.pos.y - v12 * v16 - (t.pos.y + v3 * t.yw);
          var v15 = v22 * v13 + v21 * v12;
          if (v15 < 0) {
            v13 *= -v15;
            v12 *= -v15;
            var v23 = Math.sqrt(v13 * v13 + v12 * v12);
            if (x < y) {
              lenP = x;
              y = 0;
              if (obj.pos.x - t.pos.x < 0) {
                x *= -1;
              }
            } else {
              lenP = y;
              x = 0;
              if (obj.pos.y - t.pos.y < 0) {
                y *= -1;
              }
            }
            if (lenP < v23) {
              obj.ReportCollisionVsWorld(x, y, x / lenP, y / lenP, t);
              return COL_AXIS;
            } else {
              obj.ReportCollisionVsWorld(v13, v12, t.sx, t.sy, t);
              return COL_OTHER;
            }
          }
        } else {
          if (v3 * oV < 0) {
            obj.ReportCollisionVsWorld(0, y * oV, 0, oV, t);
            return COL_AXIS;
          } else {
            var v13 = t.sx;
            var v12 = t.sy;
            var v22 = obj.pos.x - (t.pos.x - v4 * t.xw);
            var v21 = obj.pos.y - (t.pos.y + v3 * t.yw);
            var v18 = v22 * -v12 + v21 * v13;
            if (0 < v18 * v4 * v3) {
              var v11 = Math.sqrt(v22 * v22 + v21 * v21);
              var v14 = obj.r - v11;
              if (0 < v14) {
                v22 /= v11;
                v21 /= v11;
                obj.ReportCollisionVsWorld(v22 * v14, v21 * v14, v22, v21, t);
                return COL_OTHER;
              }
            } else {
              var v15 = v22 * v13 + v21 * v12;
              var v14 = obj.r - Math.abs(v15);
              if (0 < v14) {
                obj.ReportCollisionVsWorld(v13 * v14, v12 * v14, v13, v12, t);
                return COL_OTHER;
              }
            }
          }
        }
        return COL_NONE;
      }
      if (oV == 0) {
        if (v4 * oH < 0) {
          obj.ReportCollisionVsWorld(x * oH, 0, oH, 0, t);
          return COL_AXIS;
        } else {
          v22 = obj.pos.x - (t.pos.x + v4 * t.xw);
          v21 = obj.pos.y - t.pos.y;
          if (v21 * v3 < 0) {
            obj.ReportCollisionVsWorld(x * oH, 0, oH, 0, t);
            return COL_AXIS;
          } else {
            v13 = t.sx;
            v12 = t.sy;
            v18 = v22 * -v12 + v21 * v13;
            if (v18 * v4 * v3 < 0) {
              var v11 = Math.sqrt(v22 * v22 + v21 * v21);
              v14 = obj.r - v11;
              if (0 < v14) {
                v22 /= v11;
                v21 /= v11;
                obj.ReportCollisionVsWorld(v22 * v14, v21 * v14, v22, v21, t);
                return COL_OTHER;
              }
            } else {
              v15 = v22 * v13 + v21 * v12;
              v14 = obj.r - Math.abs(v15);
              if (0 < v14) {
                obj.ReportCollisionVsWorld(v13 * v14, v12 * v14, t.sx, t.sy, t);
                return COL_OTHER;
              }
            }
          }
        }
        return COL_NONE;
      }
      if (0 < v4 * oH + v3 * oV) {
        var v17 = 2.23606797749979;
        v13 = v4 * 1 / v17;
        v12 = v3 * 2 / v17;
        var v16 = obj.r;
        v22 = obj.pos.x - v13 * v16 - (t.pos.x - v4 * t.xw);
        v21 = obj.pos.y - v12 * v16 - (t.pos.y + v3 * t.yw);
        v15 = v22 * v13 + v21 * v12;
        if (v15 < 0) {
          obj.ReportCollisionVsWorld(-v13 * v15, -v12 * v15, t.sx, t.sy, t);
          return COL_OTHER;
        }
        return COL_NONE;
        return COL_NONE;
      }
      var v20 = t.pos.x + oH * t.xw;
      var v19 = t.pos.y + oV * t.yw;
      var v7 = obj.pos.x - v20;
      var v6 = obj.pos.y - v19;
      var v11 = Math.sqrt(v7 * v7 + v6 * v6);
      v14 = obj.r - v11;
      if (0 < v14) {
        if (v11 == 0) {
          v7 = oH / Math.SQRT2;
          v6 = oV / Math.SQRT2;
        } else {
          v7 /= v11;
          v6 /= v11;
        }
        obj.ReportCollisionVsWorld(v7 * v14, v6 * v14, v7, v6, t);
        return COL_OTHER;
      }
      return COL_NONE;
    }

  }

  frame 1 {
    function ProjCircle_67DegS(x, y, oH, oV, obj, t) {
      var v12 = t.signx;
      var v11 = t.signy;
      if (0 < v12 * oH) {
        return COL_NONE;
        return COL_NONE;
      }
      if (oH == 0) {
        if (oV == 0) {
          var v16 = t.sx;
          var v14 = t.sy;
          var v15 = obj.r;
          var v4 = obj.pos.x - t.pos.x;
          var v3 = obj.pos.y - (t.pos.y - v11 * t.yw);
          var v18 = v4 * -v14 + v3 * v16;
          if (v18 * v12 * v11 < 0) {
            var v13 = Math.sqrt(v4 * v4 + v3 * v3);
            var v17 = v15 - v13;
            if (0 < v17) {
              v4 /= v13;
              v3 /= v13;
              obj.ReportCollisionVsWorld(v4 * v17, v3 * v17, v4, v3, t);
              return COL_OTHER;
            }
          } else {
            v4 -= v15 * v16;
            v3 -= v15 * v14;
            var v22 = v4 * v16 + v3 * v14;
            if (v22 < 0) {
              v16 *= -v22;
              v14 *= -v22;
              var v21 = Math.sqrt(v16 * v16 + v14 * v14);
              if (x < y) {
                lenP = x;
                y = 0;
                if (obj.pos.x - t.pos.x < 0) {
                  x *= -1;
                }
              } else {
                lenP = y;
                x = 0;
                if (obj.pos.y - t.pos.y < 0) {
                  y *= -1;
                }
              }
              if (lenP < v21) {
                obj.ReportCollisionVsWorld(x, y, x / lenP, y / lenP, t);
                return COL_AXIS;
              } else {
                obj.ReportCollisionVsWorld(v16, v14, t.sx, t.sy, t);
                return COL_OTHER;
              }
            }
          }
        } else {
          if (v11 * oV < 0) {
            var v20 = t.pos.x;
            var v19 = t.pos.y - v11 * t.yw;
            var v7 = obj.pos.x - v20;
            var v6 = obj.pos.y - v19;
            if (v7 * v12 < 0) {
              obj.ReportCollisionVsWorld(0, y * oV, 0, oV, t);
              return COL_AXIS;
            } else {
              var v13 = Math.sqrt(v7 * v7 + v6 * v6);
              var v17 = obj.r - v13;
              if (0 < v17) {
                if (v13 == 0) {
                  v7 = oH / Math.SQRT2;
                  v6 = oV / Math.SQRT2;
                } else {
                  v7 /= v13;
                  v6 /= v13;
                }
                obj.ReportCollisionVsWorld(v7 * v17, v6 * v17, v7, v6, t);
                return COL_OTHER;
              }
            }
          } else {
            var v16 = t.sx;
            var v14 = t.sy;
            var v4 = obj.pos.x - (t.pos.x - v12 * t.xw);
            var v3 = obj.pos.y - (t.pos.y + oV * t.yw);
            var v18 = v4 * -v14 + v3 * v16;
            if (0 < v18 * v12 * v11) {
              var v13 = Math.sqrt(v4 * v4 + v3 * v3);
              var v17 = obj.r - v13;
              if (0 < v17) {
                v4 /= v13;
                v3 /= v13;
                obj.ReportCollisionVsWorld(v4 * v17, v3 * v17, v4, v3, t);
                return COL_OTHER;
              }
            } else {
              var v22 = v4 * v16 + v3 * v14;
              var v17 = obj.r - Math.abs(v22);
              if (0 < v17) {
                obj.ReportCollisionVsWorld(v16 * v17, v14 * v17, t.sx, t.sy, t);
                return COL_OTHER;
              }
            }
          }
        }
        return COL_NONE;
      }
      if (oV == 0) {
        obj.ReportCollisionVsWorld(x * oH, 0, oH, 0, t);
        return COL_AXIS;
        return COL_NONE;
      }
      var v20 = t.pos.x + oH * t.xw;
      var v19 = t.pos.y + oV * t.yw;
      var v7 = obj.pos.x - v20;
      var v6 = obj.pos.y - v19;
      var v13 = Math.sqrt(v7 * v7 + v6 * v6);
      v17 = obj.r - v13;
      if (0 < v17) {
        if (v13 == 0) {
          v7 = oH / Math.SQRT2;
          v6 = oV / Math.SQRT2;
        } else {
          v7 /= v13;
          v6 /= v13;
        }
        obj.ReportCollisionVsWorld(v7 * v17, v6 * v17, v7, v6, t);
        return COL_OTHER;
      }
      return COL_NONE;
    }

  }

  frame 1 {
    function ProjCircle_67DegB(x, y, oH, oV, obj, t) {
      var v4 = t.signx;
      var v3 = t.signy;
      if (oH == 0) {
        if (oV == 0) {
          var v13 = t.sx;
          var v12 = t.sy;
          var v16 = obj.r;
          var v22 = obj.pos.x - v13 * v16 - (t.pos.x + v4 * t.xw);
          var v21 = obj.pos.y - v12 * v16 - (t.pos.y - v3 * t.yw);
          var v15 = v22 * v13 + v21 * v12;
          if (v15 < 0) {
            v13 *= -v15;
            v12 *= -v15;
            var v23 = Math.sqrt(v13 * v13 + v12 * v12);
            if (x < y) {
              lenP = x;
              y = 0;
              if (obj.pos.x - t.pos.x < 0) {
                x *= -1;
              }
            } else {
              lenP = y;
              x = 0;
              if (obj.pos.y - t.pos.y < 0) {
                y *= -1;
              }
            }
            if (lenP < v23) {
              obj.ReportCollisionVsWorld(x, y, x / lenP, y / lenP, t);
              return COL_AXIS;
            } else {
              obj.ReportCollisionVsWorld(v13, v12, t.sx, t.sy, t);
              return COL_OTHER;
            }
          }
        } else {
          if (v3 * oV < 0) {
            obj.ReportCollisionVsWorld(0, y * oV, 0, oV, t);
            return COL_AXIS;
          } else {
            var v22 = obj.pos.x - t.pos.x;
            var v21 = obj.pos.y - (t.pos.y + v3 * t.yw);
            if (v22 * v4 < 0) {
              obj.ReportCollisionVsWorld(0, y * oV, 0, oV, t);
              return COL_AXIS;
            } else {
              var v13 = t.sx;
              var v12 = t.sy;
              var v18 = v22 * -v12 + v21 * v13;
              if (0 < v18 * v4 * v3) {
                var v11 = Math.sqrt(v22 * v22 + v21 * v21);
                var v14 = obj.r - v11;
                if (0 < v14) {
                  v22 /= v11;
                  v21 /= v11;
                  obj.ReportCollisionVsWorld(v22 * v14, v21 * v14, v22, v21, t);
                  return COL_OTHER;
                }
              } else {
                var v15 = v22 * v13 + v21 * v12;
                var v14 = obj.r - Math.abs(v15);
                if (0 < v14) {
                  obj.ReportCollisionVsWorld(v13 * v14, v12 * v14, v13, v12, t);
                  return COL_OTHER;
                }
              }
            }
          }
        }
        return COL_NONE;
      }
      if (oV == 0) {
        if (v4 * oH < 0) {
          obj.ReportCollisionVsWorld(x * oH, 0, oH, 0, t);
          return COL_AXIS;
        } else {
          var v17 = 2.23606797749979;
          v13 = v4 * 2 / v17;
          v12 = v3 * 1 / v17;
          v22 = obj.pos.x - (t.pos.x + v4 * t.xw);
          v21 = obj.pos.y - (t.pos.y - v3 * t.yw);
          v18 = v22 * -v12 + v21 * v13;
          if (v18 * v4 * v3 < 0) {
            var v11 = Math.sqrt(v22 * v22 + v21 * v21);
            v14 = obj.r - v11;
            if (0 < v14) {
              v22 /= v11;
              v21 /= v11;
              obj.ReportCollisionVsWorld(v22 * v14, v21 * v14, v22, v21, t);
              return COL_OTHER;
            }
          } else {
            v15 = v22 * v13 + v21 * v12;
            v14 = obj.r - Math.abs(v15);
            if (0 < v14) {
              obj.ReportCollisionVsWorld(v13 * v14, v12 * v14, t.sx, t.sy, t);
              return COL_OTHER;
            }
          }
        }
        return COL_NONE;
      }
      if (0 < v4 * oH + v3 * oV) {
        v13 = t.sx;
        v12 = t.sy;
        var v16 = obj.r;
        v22 = obj.pos.x - v13 * v16 - (t.pos.x + v4 * t.xw);
        v21 = obj.pos.y - v12 * v16 - (t.pos.y - v3 * t.yw);
        v15 = v22 * v13 + v21 * v12;
        if (v15 < 0) {
          obj.ReportCollisionVsWorld(-v13 * v15, -v12 * v15, t.sx, t.sy, t);
          return COL_OTHER;
        }
        return COL_NONE;
        return COL_NONE;
      }
      var v20 = t.pos.x + oH * t.xw;
      var v19 = t.pos.y + oV * t.yw;
      var v7 = obj.pos.x - v20;
      var v6 = obj.pos.y - v19;
      var v11 = Math.sqrt(v7 * v7 + v6 * v6);
      v14 = obj.r - v11;
      if (0 < v14) {
        if (v11 == 0) {
          v7 = oH / Math.SQRT2;
          v6 = oV / Math.SQRT2;
        } else {
          v7 /= v11;
          v6 /= v11;
        }
        obj.ReportCollisionVsWorld(v7 * v14, v6 * v14, v7, v6, t);
        return COL_OTHER;
      }
      return COL_NONE;
    }

  }

  frame 1 {
    function ResolveCircleTile(x, y, oH, oV, obj, t) {
      if (0 < t.ID) {
        return Proj_CircleTile[t.CTYPE](x, y, oH, oV, obj, t);
      } else {
        return false;
      }
    }

    Proj_CircleTile = new Object();
    Proj_CircleTile[CTYPE_FULL] = ProjCircle_Full;
    Proj_CircleTile[CTYPE_45DEG] = ProjCircle_45Deg;
    Proj_CircleTile[CTYPE_CONCAVE] = ProjCircle_Concave;
    Proj_CircleTile[CTYPE_CONVEX] = ProjCircle_Convex;
    Proj_CircleTile[CTYPE_22DEGs] = ProjCircle_22DegS;
    Proj_CircleTile[CTYPE_22DEGb] = ProjCircle_22DegB;
    Proj_CircleTile[CTYPE_67DEGs] = ProjCircle_67DegS;
    Proj_CircleTile[CTYPE_67DEGb] = ProjCircle_67DegB;
    Proj_CircleTile[CTYPE_HALF] = ProjCircle_Half;
  }

  frame 1 {
    function QueryRayObj(out, p0, p1, obj) {
      var v5 = tiles.GetTile_V(p0);
      var v25 = v5.i;
      var v24 = v5.j;
      var v4 = p1.x - p0.x;
      var v3 = p1.y - p0.y;
      var v23 = Math.sqrt(v4 * v4 + v3 * v3);
      if (v23 != 0) {
        v4 /= v23;
        v3 /= v23;
      } else {
        return false;
      }
      var v22 = v25;
      var v21 = v24;
      if (v4 < 0) {
        var v18 = -1;
        var v14 = (v5.pos.x - v5.xw - p0.x) / v4;
        var v20 = 2 * v5.xw / -v4;
      } else {
        if (0 < v4) {
          var v18 = 1;
          var v14 = (v5.pos.x + v5.xw - p0.x) / v4;
          var v20 = 2 * v5.xw / v4;
        } else {
          var v18 = 0;
          var v14 = 100000000;
          var v20 = 0;
        }
      }
      if (v3 < 0) {
        var v17 = -1;
        var v13 = (v5.pos.y - v5.yw - p0.y) / v3;
        var v19 = 2 * v5.yw / -v3;
      } else {
        if (0 < v3) {
          var v17 = 1;
          var v13 = (v5.pos.y + v5.yw - p0.y) / v3;
          var v19 = 2 * v5.yw / v3;
        } else {
          var v17 = 0;
          var v13 = 100000000;
          var v19 = 0;
        }
      }
      var v9 = p0.x;
      var v8 = p0.y;
      if (TestRayTile(out, v9, v8, v4, v3, v5)) {
        var v11 = out.x;
        var v10 = out.y;
        if (TestRay_Circle(out, p0.x, p0.y, v4, v3, obj)) {
          var v16 = (p0.x - out.x) * v4 + (p0.y - out.y) * v3;
          var v15 = (p0.x - v11) * v4 + (p0.y - v10) * v3;
          if (v16 < v15) {
            out.x = v11;
            out.y = v10;
            return false;
          } else {
            return true;
          }
        } else {
          out.x = v11;
          out.y = v10;
          return false;
        }
      }
      var v6;
      var v7;
      while (v5 != null) {
        if (v14 < v13) {
          if (v18 < 0) {
            v6 = v5.eL;
            v7 = v5.nL;
          } else {
            v6 = v5.eR;
            v7 = v5.nR;
          }
          if (0 < v6) {
            v9 = p0.x + v14 * v4;
            v8 = p0.y + v14 * v3;
            if (v6 == EID_SOLID) {
              v11 = v9;
              v10 = v8;
              if (TestRay_Circle(out, p0.x, p0.y, v4, v3, obj)) {
                var v16 = (p0.x - out.x) * v4 + (p0.y - out.y) * v3;
                var v15 = (p0.x - v11) * v4 + (p0.y - v10) * v3;
                if (v16 < v15) {
                  out.x = v11;
                  out.y = v10;
                  return false;
                } else {
                  return true;
                }
              } else {
                out.x = v11;
                out.y = v10;
                return false;
              }
            } else {
              if (TestRayTile(out, v9, v8, v4, v3, v7)) {
                v11 = out.x;
                v10 = out.y;
                if (TestRay_Circle(out, p0.x, p0.y, v4, v3, obj)) {
                  var v16 = (p0.x - out.x) * v4 + (p0.y - out.y) * v3;
                  var v15 = (p0.x - v11) * v4 + (p0.y - v10) * v3;
                  if (v16 < v15) {
                    out.x = v11;
                    out.y = v10;
                    return false;
                  } else {
                    return true;
                  }
                } else {
                  out.x = v11;
                  out.y = v10;
                  return false;
                }
              } else {}
            }
          } else {}
          v14 += v20;
          v22 += v18;
        } else {
          if (v17 < 0) {
            v6 = v5.eU;
            v7 = v5.nU;
          } else {
            v6 = v5.eD;
            v7 = v5.nD;
          }
          if (0 < v6) {
            v9 = p0.x + v13 * v4;
            v8 = p0.y + v13 * v3;
            if (v6 == EID_SOLID) {
              v11 = v9;
              v10 = v8;
              if (TestRay_Circle(out, p0.x, p0.y, v4, v3, obj)) {
                var v16 = (p0.x - out.x) * v4 + (p0.y - out.y) * v3;
                var v15 = (p0.x - v11) * v4 + (p0.y - v10) * v3;
                if (v16 < v15) {
                  out.x = v11;
                  out.y = v10;
                  return false;
                } else {
                  return true;
                }
              } else {
                out.x = v11;
                out.y = v10;
                return false;
              }
            } else {
              if (TestRayTile(out, v9, v8, v4, v3, v7)) {
                v11 = out.x;
                v10 = out.y;
                if (TestRay_Circle(out, p0.x, p0.y, v4, v3, obj)) {
                  var v16 = (p0.x - out.x) * v4 + (p0.y - out.y) * v3;
                  var v15 = (p0.x - v11) * v4 + (p0.y - v10) * v3;
                  if (v16 < v15) {
                    out.x = v11;
                    out.y = v10;
                    return false;
                  } else {
                    return true;
                  }
                } else {
                  out.x = v11;
                  out.y = v10;
                  return false;
                }
              } else {}
            }
          } else {}
          v13 += v19;
          v21 += v17;
        }
        v5 = v7;
      }
      if (TestRay_Circle(out, p0.x, p0.y, v4, v3, obj)) {
        return true;
      }
      return false;
    }

  }

  frame 1 {
    function CollideRayvsMap(out, p0, p1) {
      var v2 = tiles.GetTile_V(p0);
      var v40 = v2.i;
      var v39 = v2.j;
      var v6 = p1.x - p0.x;
      var v5 = p1.y - p0.y;
      var v38 = Math.sqrt(v6 * v6 + v5 * v5);
      if (v38 != 0) {
        v6 /= v38;
        v5 /= v38;
      } else {
        return false;
      }
      if (v6 < 0) {
        var v21 = -1;
        var v20 = (v2.pos.x - v2.xw - p0.x) / v6;
        var v35 = 2 * v2.xw / -v6;
      } else {
        if (0 < v6) {
          var v21 = 1;
          var v20 = (v2.pos.x + v2.xw - p0.x) / v6;
          var v35 = 2 * v2.xw / v6;
        } else {
          var v21 = 0;
          var v20 = 100000000;
          var v35 = 0;
        }
      }
      if (v5 < 0) {
        var v17 = -1;
        var v19 = (v2.pos.y - v2.yw - p0.y) / v5;
        var v34 = 2 * v2.yw / -v5;
      } else {
        if (0 < v5) {
          var v17 = 1;
          var v19 = (v2.pos.y + v2.yw - p0.y) / v5;
          var v34 = 2 * v2.yw / v5;
        } else {
          var v17 = 0;
          var v19 = 100000000;
          var v34 = 0;
        }
      }
      var v37 = v40;
      var v36 = v39;
      var v11;
      var v10;
      var v42;
      var v41;
      v42 = p0.x;
      v11 = v42;
      v41 = p0.y;
      v10 = v41;
      if (TestRayTile(out, v42, v41, v6, v5, v2)) {
        return true;
      }
      static_rend.SetStyle(0, 8947848, 100);
      var v18 = new Vector2(0, 0);
      var v4 = new Vector2(v11, v10);
      var v7;
      var v9;
      var v3;
      var v25;
      var v13;
      var v16;
      var v32;
      var v31;
      var v24 = false;
      var v12 = false;
      var v30 = false;
      var v22 = false;
      var v23 = false;
      var v27;
      var v26;
      var v15;
      var v14;
      var v29;
      var v28;
      while (v2 != null) {
        v18.x = v4.x;
        v18.y = v4.y;
        if (v20 < v19) {
          v4.x = v11 + v20 * v6;
          v4.y = v10 + v20 * v5;
          static_rend.DrawPlus(v4);
          if (v21 < 0) {
            v7 = v2.eL;
            v9 = v2.nL;
          } else {
            v7 = v2.eR;
            v9 = v2.nR;
          }
          if (!v12 && 0 < v7) {
            if (v7 == EID_SOLID) {
              out.x = v4.x;
              out.y = v4.y;
              v24 = true;
              v29 = out.x;
              v28 = out.y;
            } else {
              if (TestRayTile(out, v4.x, v4.y, v6, v5, v9)) {
                v12 = true;
                v27 = out.x;
                v26 = out.y;
              } else {}
            }
          } else {}
          v20 += v35;
          v37 += v21;
        } else {
          v4.x = v11 + v19 * v6;
          v4.y = v10 + v19 * v5;
          static_rend.DrawPlus(v4);
          if (v17 < 0) {
            v7 = v2.eU;
            v9 = v2.nU;
          } else {
            v7 = v2.eD;
            v9 = v2.nD;
          }
          if (!v12 && 0 < v7) {
            if (v7 == EID_SOLID) {
              out.x = v4.x;
              out.y = v4.y;
              v24 = true;
              v29 = out.x;
              v28 = out.y;
            } else {
              if (TestRayTile(out, v4.x, v4.y, v6, v5, v9)) {
                v12 = true;
                v27 = out.x;
                v26 = out.y;
              } else {}
            }
          } else {}
          v19 += v34;
          v36 += v17;
        }
        if (v21 < 0) {
          if (v17 < 0) {
            v16 = v2.nR.nU;
            v13 = v2.nL.nD;
          } else {
            v16 = v2.nL.nU;
            v13 = v2.nR.nD;
          }
        } else {
          if (v17 < 0) {
            v16 = v2.nR.nD;
            v13 = v2.nL.nU;
          } else {
            v16 = v2.nL.nD;
            v13 = v2.nR.nU;
          }
        }
        v32 = v18.x - v2.pos.x;
        v31 = v18.y - v2.pos.y;
        if (v32 * -v5 + v31 * v6 < 0) {
          v25 = v13;
        } else {
          v25 = v16;
        }
        v3 = v2.next;
        var v8 = null;
        while (v3 != null) {
          if (TestRayObj(out, v11, v10, v6, v5, v3)) {
            v8 = v3;
            v22 = true;
            v15 = out.x;
            v14 = out.y;
            break;
          }
          v3 = v3.next;
        }
        v3 = v25.next;
        while (v3 != null) {
          if (TestRayObj(out, v11, v10, v6, v5, v3)) {
            v8 = v3;
            v23 = true;
            v15 = out.x;
            v14 = out.y;
            break;
          }
          v3 = v3.next;
        }
        if (v22 || v23) {
          out.x = v15;
          out.y = v14;
          v8.pos.x += v6 * 3;
          v8.pos.y += v5 * 3;
          return true;
        } else {
          if (v30) {
            out.x = v27;
            out.y = v26;
            return true;
          } else {
            if (v24) {
              out.x = v29;
              out.y = v28;
              return true;
            }
          }
        }
        if (v12) {
          v30 = true;
        }
        v2 = v9;
      }
      return false;
    }

  }

  frame 1 {
    function CollideRayvsTiles(out, p0, p1) {
      var v1 = tiles.GetTile_V(p0);
      var v20 = v1.i;
      var v19 = v1.j;
      var v8 = p1.x - p0.x;
      var v7 = p1.y - p0.y;
      var v18 = Math.sqrt(v8 * v8 + v7 * v7);
      if (v18 != 0) {
        v8 /= v18;
        v7 /= v18;
      } else {
        return false;
      }
      var v17 = v20;
      var v16 = v19;
      if (v8 < 0) {
        var v13 = -1;
        var v11 = (v1.pos.x - v1.xw - p0.x) / v8;
        var v15 = 2 * v1.xw / -v8;
      } else {
        if (0 < v8) {
          var v13 = 1;
          var v11 = (v1.pos.x + v1.xw - p0.x) / v8;
          var v15 = 2 * v1.xw / v8;
        } else {
          var v13 = 0;
          var v11 = 100000000;
          var v15 = 0;
        }
      }
      if (v7 < 0) {
        var v12 = -1;
        var v10 = (v1.pos.y - v1.yw - p0.y) / v7;
        var v14 = 2 * v1.yw / -v7;
      } else {
        if (0 < v7) {
          var v12 = 1;
          var v10 = (v1.pos.y + v1.yw - p0.y) / v7;
          var v14 = 2 * v1.yw / v7;
        } else {
          var v12 = 0;
          var v10 = 100000000;
          var v14 = 0;
        }
      }
      var v5 = p0.x;
      var v4 = p0.y;
      if (TestRayTile(out, v5, v4, v8, v7, v1)) {
        return true;
      }
      var v2;
      var v3;
      while (v1 != null) {
        if (v11 < v10) {
          if (v13 < 0) {
            v2 = v1.eL;
            v3 = v1.nL;
          } else {
            v2 = v1.eR;
            v3 = v1.nR;
          }
          if (0 < v2) {
            v5 = p0.x + v11 * v8;
            v4 = p0.y + v11 * v7;
            if (v2 == EID_SOLID) {
              out.x = v5;
              out.y = v4;
              return true;
            } else {
              if (TestRayTile(out, v5, v4, v8, v7, v3)) {
                return true;
              } else {}
            }
          } else {}
          v11 += v15;
          v17 += v13;
        } else {
          if (v12 < 0) {
            v2 = v1.eU;
            v3 = v1.nU;
          } else {
            v2 = v1.eD;
            v3 = v1.nD;
          }
          if (0 < v2) {
            v5 = p0.x + v10 * v8;
            v4 = p0.y + v10 * v7;
            if (v2 == EID_SOLID) {
              out.x = v5;
              out.y = v4;
              return true;
            } else {
              if (TestRayTile(out, v5, v4, v8, v7, v3)) {
                return true;
              } else {}
            }
          } else {}
          v10 += v14;
          v16 += v12;
        }
        v1 = v3;
      }
      return false;
    }

  }

  frame 1 {
    function TestRay_Circle(out, px, py, dx, dy, obj) {
      var v6 = px - obj.pos.x;
      var v5 = py - obj.pos.y;
      var v11 = dx * dx + dy * dy;
      var v4 = 2 * (dx * v6 + dy * v5);
      var v12 = obj.r;
      var v14 = v6 * v6 + v5 * v5 - v12 * v12;
      var v9 = v4 * v4 - 4 * v11 * v14;
      if (0 <= v9) {
        var v13 = Math.sqrt(v9);
        var v10 = 1 / 2 * v11;
        var v1 = (-v4 + v13) * v10;
        var v3 = (-v4 - v13) * v10;
        var v2;
        if (v3 < 0) {
          if (v1 < 0) {
            return false;
          } else {
            v2 = v1;
          }
        } else {
          if (v1 < 0) {
            v2 = v3;
          } else {
            if (v3 < v1) {
              v2 = v3;
            } else {
              v2 = v1;
            }
          }
        }
        out.x = px + v2 * dx;
        out.y = py + v2 * dy;
        return true;
        return false;
      }
      return false;
      return false;
    }

  }

  frame 1 {
    function TestRay_AABB(out, px, py, dx, dy, obj) {
      var v4 = obj.pos.x;
      var v2 = obj.pos.y;
      var v6 = obj.xw;
      var v7 = obj.yw;
      var v9;
      var v8;
      if (px < v4) {
        v9 = v4 - v6;
      } else {
        v9 = v4 + v6;
      }
      if (py < v2) {
        v8 = v2 - v7;
      } else {
        v8 = v2 + v7;
      }
      var v1;
      var v13;
      var v11;
      var v12;
      var v10;
      if (dx == 0) {
        if (dy == 0) {
          return false;
        } else {
          v13 = v4 - v6;
          v12 = v4 + v6;
          v10 = v8;
          v11 = v10;
          v1 = (v8 - py) / dy;
        }
      } else {
        if (dy == 0) {
          v11 = v2 - v7;
          v10 = v2 + v7;
          v12 = v9;
          v13 = v12;
          v1 = (v9 - px) / dx;
        } else {
          var v19 = (v9 - px) / dx;
          var v18 = (v8 - py) / dy;
          if (v19 < v18) {
            v13 = v4 - v6;
            v12 = v4 + v6;
            v10 = v8;
            v11 = v10;
            v1 = v18;
          } else {
            v11 = v2 - v7;
            v10 = v2 + v7;
            v12 = v9;
            v13 = v12;
            v1 = v19;
          }
        }
      }
      if (0 < v1) {
        var v22 = px + 100 * dx;
        var v20 = py + 100 * dy;
        var v17 = (v22 - px) * (v11 - py) - (v13 - px) * (v20 - py);
        var v16 = (v22 - px) * (v10 - py) - (v12 - px) * (v20 - py);
        if (v17 * v16 < 0) {
          out.x = px + v1 * dx;
          out.y = py + v1 * dy;
          return true;
        } else {
          return false;
        }
        return false;
      }
      return false;
      return false;
    }

  }

  frame 1 {
    function TestRay_Full(out, px, py, dx, dy, t) {
      return false;
    }

  }

  frame 1 {
    function TestRay_45Deg(out, px, py, dx, dy, t) {
      var v6 = t.signx;
      var v5 = t.signy;
      if (0 <= v6 * dx + v5 * dy) {
        return false;
        return false;
      }
      var v4 = v6 * t.xw;
      var v3 = -v5 * t.yw;
      var v8 = t.pos.x - px;
      var v7 = t.pos.y - py;
      var v2 = (dy * v8 - dx * v7) / (dx * v3 - dy * v4);
      if (Math.abs(v2) <= 1) {
        out.x = t.pos.x + v2 * v4;
        out.y = t.pos.y + v2 * v3;
        return true;
        return false;
      }
      return false;
      return false;
    }

  }

  frame 1 {
    function TestRay_Concave(out, px, py, dx, dy, t) {
      var v17 = t.signx;
      var v15 = t.signy;
      if (0 <= v17 * dx + v15 * dy) {
        return false;
        return false;
      }
      var v13 = v17 * t.xw;
      var v12 = -v15 * t.yw;
      var v10 = t.pos.x - px;
      var v9 = t.pos.y - py;
      var v14 = (dy * v10 - dx * v9) / (dx * v12 - dy * v13);
      if (Math.abs(v14) <= 1) {
        var v6 = -v13 - v10;
        var v5 = v12 - v9;
        var v16 = dx * dx + dy * dy;
        var v4 = 2 * (dx * v6 + dy * v5);
        var v18 = t.xw * 2;
        var v22 = v6 * v6 + v5 * v5 - v18 * v18;
        var v19 = v4 * v4 - 4 * v16 * v22;
        if (0 <= v19) {
          var v21 = Math.sqrt(v19);
          var v11 = 1 / 2 * v16;
          var v8 = (-v4 + v21) * v11;
          var v7 = (-v4 - v21) * v11;
          if (v7 < v8) {
            out.x = px + v8 * dx;
            out.y = py + v8 * dy;
          } else {
            out.x = px + v7 * dx;
            out.y = py + v7 * dy;
          }
          return true;
        } else {
          return false;
        }
        return false;
      }
      return false;
      return false;
    }

  }

  frame 1 {
    function TestRay_Convex(out, px, py, dx, dy, t) {
      var v17 = t.signx;
      var v16 = t.signy;
      var v9 = px - (t.pos.x - v17 * t.xw);
      var v8 = py - (t.pos.y - v16 * t.yw);
      var v11 = dx * dx + dy * dy;
      var v2 = 2 * (dx * v9 + dy * v8);
      var v12 = t.xw * 2;
      var v15 = v9 * v9 + v8 * v8 - v12 * v12;
      var v7 = v2 * v2 - 4 * v11 * v15;
      if (0 <= v7) {
        var v14 = Math.sqrt(v7);
        var v10 = 1 / 2 * v11;
        var v4 = (-v2 + v14) * v10;
        var v3 = (-v2 - v14) * v10;
        if (v3 < v4) {
          out.x = px + v3 * dx;
          out.y = py + v3 * dy;
        } else {
          out.x = px + v4 * dx;
          out.y = py + v4 * dy;
        }
        return true;
        return false;
      }
      return false;
      return false;
    }

  }

  frame 1 {
    function TestRay_Half(out, px, py, dx, dy, t) {
      var v4 = t.signx;
      var v3 = t.signy;
      var v6 = t.pos.x - px;
      var v5 = t.pos.y - py;
      if (0 <= v6 * v4 + v5 * v3) {
        out.x = px;
        out.y = py;
        return true;
        return false;
      }
      if (0 <= v4 * dx + v3 * dy) {
        return false;
        return false;
      }
      var v8 = v3 * t.xw;
      var v7 = v4 * t.yw;
      var v2 = (dy * v6 - dx * v5) / (dx * v7 - dy * v8);
      if (Math.abs(v2) <= 1) {
        out.x = t.pos.x + v2 * v8;
        out.y = t.pos.y + v2 * v7;
        return true;
        return false;
      }
      return false;
      return false;
    }

  }

  frame 1 {
    function TestRay_22DegS(out, px, py, dx, dy, t) {
      var v14 = t.sx;
      var v12 = t.sy;
      var v3 = t.signx;
      var v6 = t.signy;
      var v5 = t.pos.x - v3 * t.xw - px;
      var v4 = t.pos.y - py;
      if (0 <= v5 * v3 && 0 <= v4 * v6) {
        out.x = px;
        out.y = py;
        return true;
        return false;
      }
      if (0 <= v14 * dx + v12 * dy) {
        return false;
        return false;
      }
      v5 += v3 * t.xw;
      var v7 = v6 * 0.5 * t.yw;
      v4 -= v7;
      var v9 = -v6 * t.xw;
      var v8 = 0.5 * v3 * t.yw;
      var v2 = (dy * v5 - dx * v4) / (dx * v8 - dy * v9);
      if (Math.abs(v2) <= 1) {
        out.x = t.pos.x + v2 * v9;
        out.y = t.pos.y - v7 + v2 * v8;
        return true;
        return false;
      }
      return false;
      return false;
    }

  }

  frame 1 {
    function TestRay_22DegB(out, px, py, dx, dy, t) {
      var v14 = t.sx;
      var v12 = t.sy;
      var v10 = t.signx;
      var v4 = t.signy;
      var v5 = t.pos.x - px;
      var v3 = t.pos.y - py;
      if (v5 * v10 <= 0 && 0 <= v3 * v4) {
        out.x = px;
        out.y = py;
        return true;
        return false;
      }
      if (0 <= v14 * dx + v12 * dy) {
        return false;
        return false;
      }
      var v6 = v4 * 0.5 * t.yw;
      v3 += v6;
      var v8 = -v4 * t.xw;
      var v7 = 0.5 * v10 * t.yw;
      var v2 = (dy * v5 - dx * v3) / (dx * v7 - dy * v8);
      if (Math.abs(v2) <= 1) {
        out.x = t.pos.x + v2 * v8;
        out.y = t.pos.y + v6 + v2 * v7;
        return true;
        return false;
      }
      return false;
      return false;
    }

  }

  frame 1 {
    function TestRay_67DegS(out, px, py, dx, dy, t) {
      var v14 = t.sx;
      var v12 = t.sy;
      var v6 = t.signx;
      var v3 = t.signy;
      var v5 = t.pos.x - px;
      var v4 = t.pos.y - v3 * t.yw - py;
      if (0 <= v5 * v6 && 0 <= v4 * v3) {
        out.x = px;
        out.y = py;
        return true;
        return false;
      }
      if (0 <= v14 * dx + v12 * dy) {
        return false;
        return false;
      }
      v4 += v3 * t.yw;
      var v7 = v6 * 0.5 * t.xw;
      v5 -= v7;
      var v9 = -0.5 * v3 * t.xw;
      var v8 = v6 * t.yw;
      var v2 = (dy * v5 - dx * v4) / (dx * v8 - dy * v9);
      if (Math.abs(v2) <= 1) {
        out.x = t.pos.x - v7 + v2 * v9;
        out.y = t.pos.y + v2 * v8;
        return true;
        return false;
      }
      return false;
      return false;
    }

  }

  frame 1 {
    function TestRay_67DegB(out, px, py, dx, dy, t) {
      var v14 = t.sx;
      var v12 = t.sy;
      var v4 = t.signx;
      var v10 = t.signy;
      var v3 = t.pos.x - px;
      var v5 = t.pos.y - py;
      if (v5 * v10 <= 0 && 0 <= v3 * v4) {
        out.x = px;
        out.y = py;
        return true;
        return false;
      }
      if (0 <= v14 * dx + v12 * dy) {
        return false;
        return false;
      }
      var v6 = v4 * 0.5 * t.xw;
      v3 += v6;
      var v8 = -0.5 * v10 * t.xw;
      var v7 = v4 * t.yw;
      var v2 = (dy * v3 - dx * v5) / (dx * v7 - dy * v8);
      if (Math.abs(v2) <= 1) {
        out.x = t.pos.x + v6 + v2 * v8;
        out.y = t.pos.y + v2 * v7;
        return true;
        return false;
      }
      return false;
      return false;
    }

  }

  frame 1 {
    function TestRayTile(out, px, py, dx, dy, t) {
      if (0 < t.ID) {
        return TestRay_Tile[t.CTYPE](out, px, py, dx, dy, t);
      } else {
        return false;
      }
    }

    TestRay_Tile = new Object();
    TestRay_Tile[CTYPE_FULL] = TestRay_Full;
    TestRay_Tile[CTYPE_45DEG] = TestRay_45Deg;
    TestRay_Tile[CTYPE_CONCAVE] = TestRay_Concave;
    TestRay_Tile[CTYPE_CONVEX] = TestRay_Convex;
    TestRay_Tile[CTYPE_22DEGs] = TestRay_22DegS;
    TestRay_Tile[CTYPE_22DEGb] = TestRay_22DegB;
    TestRay_Tile[CTYPE_67DEGs] = TestRay_67DegS;
    TestRay_Tile[CTYPE_67DEGb] = TestRay_67DegB;
    TestRay_Tile[CTYPE_HALF] = TestRay_Half;
  }

  frame 1 {
    function TestRayObj(out, px, py, dx, dy, obj) {
      if (obj.OTYPE == OTYPE_AABB) {
        return TestRay_AABB(out, px, py, dx, dy, obj);
      } else {
        return TestRay_Circle(out, px, py, dx, dy, obj);
      }
    }

  }

  frame 1 {
    function ObjectManager() {
      this.InitDataStructs();
    }

    ObjectManager.prototype.InitDataStructs = function () {
      this.objList = new Object();
      this.objArray = new Array();
      this.numObjs = 0;
      this.nextID = 0;
      this.gridList = new Object();
      this.gridNum = 0;
      this.updateList = new Object();
      this.updateNum = 0;
      this.drawList = new Object();
      this.drawNum = 0;
      this.thinkList = new Object();
      this.thinkNum = 0;
      this.curThinker = null;
      this.thinkRate = 2;
      this.thinkTimer = 0;
    };

    ObjectManager.prototype.Register = function (obj) {
      obj.UID = this.nextID++;
      this.objList[obj.UID] = obj;
      this.objArray.push(obj);
      ++this.numObjs;
    };

    ObjectManager.prototype.AddToGrid = function (obj) {
      obj.cell = tiles.GetTile_V(obj.pos);
      obj.cell.InsertObj(obj);
      this.gridList[obj.UID] = obj;
      ++this.gridNum;
    };

    ObjectManager.prototype.RemoveFromGrid = function (obj) {
      if (this.gridList[obj.UID] != null) {
        obj.cell.RemoveObj(obj);
        delete this.gridList[obj.UID];
        --this.gridNum;
      } else {}
    };

    ObjectManager.prototype.Moved = function (obj) {
      var v2 = obj.cell;
      n = tiles.GetTile_V(obj.pos);
      if (v2 != n) {
        v2.RemoveObj(obj);
        obj.cell = n;
        n.InsertObj(obj);
        return true;
      } else {
        return false;
      }
    };

    ObjectManager.prototype.GetObj = function (ID) {
      var v3 = this.objList[ID];
      if (v3 == null) {
      } else {
        return this.objList[ID];
      }
    };

    ObjectManager.prototype.GetObjType = function (obj) {
      return obj.OBJ_TYPE;
    };

    ObjectManager.prototype.IdleObjectsAfterDeath = function () {
      for (var v2 in this.objList) {
        this.objList[v2].IdleAfterDeath();
      }
    };

    ObjectManager.prototype.DumpThinkList = function () {
      var v4 = 'THINK LIST:\n';
      var v6 = this.curThinker;
      var v5 = v6.UID;
      v4 += 'head: ' + v5;
      v4 += '\n' + v6.prevThinker.UID + '<-' + v5 + '->' + v6.nextThinker.UID;
      if (this.thinkNum == 0) {
        v4 += 'no thinkers!';
        return v4;
      }
      var v3 = '   ';
      var v2 = v6.nextThinker;
      while (v2.UID != v5) {
        v4 += '\n' + v3 + v2.prevThinker.UID + '<-' + v2.UID + '->' + v2.nextThinker.UID;
        v2 = v2.nextThinker;
        v3 += '   ';
      }
      return v4;
    };

    ObjectManager.prototype.Tick = function () {
      if (0 < this.updateNum) {
        for (var v2 in this.updateList) {
          this.updateList[v2].Update();
        }
      }
      if (0 < this.thinkNum) {
        if (this.thinkRate < this.thinkTimer) {
          this.thinkTimer = 0;
          this.curThinker.Think();
          this.curThinker = this.curThinker.nextThinker;
        } else {
          ++this.thinkTimer;
        }
      }
    };

    ObjectManager.prototype.StartUpdate = function (obj) {
      if (this.updateList[obj.UID] == null) {
        this.updateList[obj.UID] = obj;
        ++this.updateNum;
      }
    };

    ObjectManager.prototype.EndUpdate = function (obj) {
      if (this.updateList[obj.UID] == null) {
        return undefined;
      }
      delete this.updateList[obj.UID];
      --this.updateNum;
    };

    ObjectManager.prototype.StartDraw = function (obj) {
      if (this.drawList[obj.UID] == null) {
        this.drawList[obj.UID] = obj;
        ++this.drawNum;
      }
    };

    ObjectManager.prototype.EndDraw = function (obj) {
      if (this.drawList[obj.UID] == null) {
        return undefined;
      }
      delete this.drawList[obj.UID];
      --this.drawNum;
    };

    ObjectManager.prototype.StartThink = function (obj) {
      if (this.thinkList[obj.UID] == null) {
        this.thinkList[obj.UID] = obj;
        ++this.thinkNum;
        if (this.thinkNum == 1) {
          this.curThinker = obj;
          obj.nextThinker = obj;
          obj.prevThinker = obj;
        } else {
          obj.nextThinker = this.curThinker;
          obj.prevThinker = this.curThinker.prevThinker;
          obj.prevThinker.nextThinker = obj;
          obj.nextThinker.prevThinker = obj;
          this.curThinker = obj;
        }
      }
    };

    ObjectManager.prototype.EndThink = function (obj) {
      if (this.thinkList[obj.UID] == null) {
        return undefined;
      }
      delete this.thinkList[obj.UID];
      --this.thinkNum;
      if (this.thinkNum <= 0) {
        obj.nextThinker = null;
        obj.prevThinker = null;
        this.curThinker = null;
        this.thinkNum = 0;
      } else {
        obj.nextThinker.prevThinker = obj.prevThinker;
        obj.prevThinker.nextThinker = obj.nextThinker;
        if (obj == this.curThinker) {
          this.curThinker = obj.nextThinker;
        }
        obj.nextThinker = null;
        obj.prevThinker = null;
      }
    };

    ObjectManager.prototype.Clear = function () {
      for (var v2 in this.thinkList) {
        this.EndThink(this.thinkList[v2]);
      }
      for (v2 in this.gridList) {
        this.RemoveFromGrid(this.gridList[v2]);
      }
      for (v2 in this.updateList) {
        this.EndUpdate(this.updateList[v2]);
      }
      for (v2 in this.drawList) {
        this.EndDraw(this.drawList[v2]);
      }
      for (v2 in this.objArray) {
        delete this.objArray[v2];
      }
      for (v2 in this.objList) {
        this.objList[v2].next = null;
        this.objList[v2].prev = null;
        this.objList[v2].nextThinker = null;
        this.objList[v2].prevThinker = null;
        this.objList[v2].UnInit();
        this.objList[v2].Destruct();
        delete this.objList[v2];
      }
      tiles.ClearGrid();
      delete this.objList;
      delete this.objArray;
      delete this.updateList;
      delete this.drawList;
      delete this.gridList;
      delete this.thinkList;
      delete this.curThinker;
      this.InitDataStructs();
    };

    ObjectManager.prototype.Draw = function () {
      for (var v2 in this.drawList) {
        this.drawList[v2].Draw();
      }
    };

  }

  frame 1 {
    OBJTYPE_GOLD = 0;
    OBJTYPE_BOUNCEBLOCK = 1;
    OBJTYPE_LAUNCHPAD = 2;
    OBJTYPE_TURRET = 3;
    OBJTYPE_FLOORGUARD = 4;
    OBJTYPE_PLAYER = 5;
    OBJTYPE_DRONE = 6;
    OBJTYPE_ONEWAYPLATFORM = 7;
    OBJTYPE_THWOMP = 8;
    OBJTYPE_TESTDOOR = 9;
    OBJTYPE_HOMINGLAUNCHER = 10;
    OBJTYPE_EXIT = 11;
    OBJTYPE_MINE = 12;
    ObjectManager.prototype.GetObjectStates = function () {
      var v3 = '';
      var v2 = 0;
      while (v2 < this.objArray.length) {
        v3 += this.objArray[v2].OBJ_TYPE;
        v3 += OBJTYPE_SEPERATION_CHAR;
        v3 += this.objArray[v2].DumpInitData();
        v3 += OBJECT_SEPERATION_CHAR;
        ++v2;
      }
      if (0 < v3.length) {
        var v4 = v3.lastIndexOf(OBJECT_SEPERATION_CHAR);
        v3 = v3.substring(0, v4);
      }
      return v3;
    };

    ObjectManager.prototype.SpawnGameObject = function (OBJ_TYPE, params) {
      var v2 = this.BuildObject(OBJ_TYPE);
      v2.OBJ_TYPE = OBJ_TYPE;
      v2.Init(params);
      return v2.UID;
    };

    ObjectManager.prototype.BuildObject = function (OBJ_TYPE) {
      if (OBJ_TYPE == OBJTYPE_PLAYER) {
        var v2 = new PlayerObject();
        return v2;
      } else {
        if (OBJ_TYPE == OBJTYPE_GOLD) {
          var v2 = new GoldObject();
          return v2;
        } else {
          if (OBJ_TYPE == OBJTYPE_BOUNCEBLOCK) {
            var v2 = new BounceBlockObject();
            return v2;
          } else {
            if (OBJ_TYPE == OBJTYPE_LAUNCHPAD) {
              var v2 = new LaunchPadObject();
              return v2;
            } else {
              if (OBJ_TYPE == OBJTYPE_TURRET) {
                var v2 = new TurretObject();
                return v2;
              } else {
                if (OBJ_TYPE == OBJTYPE_FLOORGUARD) {
                  var v2 = new FloorGuardObject();
                  return v2;
                } else {
                  if (OBJ_TYPE == OBJTYPE_DRONE) {
                    var v2 = new DroneObject();
                    return v2;
                  } else {
                    if (OBJ_TYPE == OBJTYPE_ONEWAYPLATFORM) {
                      var v2 = new OneWayPlatformObject();
                      return v2;
                    } else {
                      if (OBJ_TYPE == OBJTYPE_THWOMP) {
                        var v2 = new ThwompObject();
                        return v2;
                      } else {
                        if (OBJ_TYPE == OBJTYPE_TESTDOOR) {
                          var v2 = new TestDoorObject();
                          return v2;
                        } else {
                          if (OBJ_TYPE == OBJTYPE_HOMINGLAUNCHER) {
                            var v2 = new HomingLauncherObject();
                            return v2;
                          } else {
                            if (OBJ_TYPE == OBJTYPE_EXIT) {
                              var v2 = new ExitObject();
                              return v2;
                            } else {
                              if (OBJ_TYPE == OBJTYPE_MINE) {
                                var v2 = new MineObject();
                                return v2;
                              } else {}
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    };

  }

  frame 1 {
    function ExitObject() {
      this.name = 'exit';
      this.pos = new Vector2(24, 55);
      this.trigger = new Object();
      this.trigger.pos = new Vector2(87, 39);
      this.trigger.r = tiles.xw * 0.5;
      this.isOpen = false;
      this.r = tiles.xw;
      objects.Register(this);
      this.mc = gfx.CreateSprite('debugExitMC', LAYER_WALLS);
      this.mc._visible = false;
      this.trigger.mc = gfx.CreateSprite('debugExitTriggerMC', LAYER_WALLS);
      this.trigger.mc._visible = false;
    }

    TREASURE_RADIUS = 4;
    ExitObject.prototype.Destruct = function () {
      gfx.DestroyMC(this.mc);
      delete this.mc;
      gfx.DestroyMC(this.trigger.mc);
      delete this.trigger.mc;
      delete this.trigger;
    };

    ExitObject.prototype.Init = function (params) {
      if (params.length != 4) {
      } else {
        this.pos.x = params[0];
        this.pos.y = params[1];
        this.trigger.pos.x = params[2];
        this.trigger.pos.y = params[3];
        this.trigger.exit = this;
        this.isOpen = false;
        this.mc._yscale = this.r * 2;
        this.mc._xscale = this.mc._yscale;
        this.mc._x = this.pos.x;
        this.mc._y = this.pos.y;
        this.mc.gotoAndStop('exit_closed');
        this.mc._visible = true;
        this.trigger.mc._yscale = this.trigger.r * 2;
        this.trigger.mc._xscale = this.trigger.mc._yscale;
        this.trigger.mc._x = this.trigger.pos.x;
        this.trigger.mc._y = this.trigger.pos.y;
        this.trigger.mc.gotoAndStop('exit_closed');
        this.trigger.mc._visible = true;
        this.trigger.TestVsPlayer = this.TestVsPlayer_Trigger;
        this.TestVsPlayer = this.TestVsPlayer_Exit;
        objects.AddToGrid(this.trigger);
        objects.Moved(this.trigger);
      }
    };

    ExitObject.prototype.UnInit = function () {
      objects.RemoveFromGrid(this);
      objects.RemoveFromGrid(this.trigger);
    };

    ExitObject.prototype.DumpInitData = function () {
      var v2 = '' + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y + OBJPARAM_SEPERATION_CHAR + this.trigger.pos.x + OBJPARAM_SEPERATION_CHAR + this.trigger.pos.y;
      return v2;
    };

    ExitObject.prototype.IdleAfterDeath = function () {
      objects.RemoveFromGrid(this);
      objects.RemoveFromGrid(this.trigger);
    };

    ExitObject.prototype.TestVsPlayer_Exit = function (guy) {
      if (this.isOpen) {
        var v5 = guy.pos;
        var v3 = this.pos.x - guy.pos.x;
        var v2 = this.pos.y - guy.pos.y;
        if (Math.sqrt(v3 * v3 + v2 * v2) < this.r + guy.r) {
          this.PlayerHitExit();
        }
      }
    };

    ExitObject.prototype.TestVsPlayer_Trigger = function (guy) {
      if (!this.exit.isOpen) {
        var v5 = guy.pos;
        var v3 = this.pos.x - guy.pos.x;
        var v2 = this.pos.y - guy.pos.y;
        if (Math.sqrt(v3 * v3 + v2 * v2) < this.r + guy.r) {
          this.exit.PlayerHitTrigger();
        }
      }
    };

    ExitObject.prototype.PlayerHitExit = function () {
      player.Celebrate();
      App_LevelPassedEvent();
    };

    ExitObject.prototype.PlayerHitTrigger = function () {
      this.mc.gotoAndPlay('exit_opening');
      this.isOpen = true;
      this.trigger.mc.gotoAndStop('exit_open');
      objects.RemoveFromGrid(this.trigger);
      objects.AddToGrid(this);
      objects.Moved(this);
    };

  }

  frame 1 {
    function Init_Hacky_GoldSound() {
      _global.goldSnd = gfx.CreateSprite('debugGoldSoundMC', LAYER_PLAYER);
    }

    function GoldObject() {
      this.name = 'gold';
      this.pos = new Vector2(14, 65);
      this.isCollected = false;
      this.r = tiles.xw * 0.5;
      objects.Register(this);
      this.mc = gfx.CreateSprite('debugGoldMC', LAYER_OBJECTS);
      this.mc._visible = false;
    }

    GoldObject.prototype.Destruct = function () {
      gfx.DestroyMC(this.mc);
      delete this.mc;
    };

    GoldObject.prototype.Init = function (params) {
      if (params.length != 2) {
      } else {
        this.pos.x = params[0];
        this.pos.y = params[1];
        this.isCollected = false;
        this.mc._yscale = this.r;
        this.mc._xscale = this.mc._yscale;
        this.mc._x = this.pos.x;
        this.mc._y = this.pos.y;
        this.mc._visible = true;
        this.mc.gotoAndStop('NOT_COLLECTED');
        objects.AddToGrid(this);
        objects.Moved(this);
      }
    };

    GoldObject.prototype.UnInit = function () {
      objects.RemoveFromGrid(this);
    };

    GoldObject.prototype.DumpInitData = function () {
      var v2 = '' + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y;
      return v2;
    };

    GoldObject.prototype.IdleAfterDeath = function () {
      if (!this.isCollected) {
        objects.RemoveFromGrid(this);
      }
    };

    GoldObject.prototype.TestVsPlayer = function (guy) {
      var v5 = guy.pos;
      var v3 = this.pos.x - guy.pos.x;
      var v2 = this.pos.y - guy.pos.y;
      if (Math.sqrt(v3 * v3 + v2 * v2) < this.r + guy.r) {
        this.Dissapear();
      }
    };

    GoldObject.prototype.Dissapear = function () {
      this.isCollected = true;
      objects.RemoveFromGrid(this);
      this.mc.gotoAndPlay('COLLECTED');
      _global.goldSnd.gotoAndPlay('COLLECTED');
      game.GiveBonusTime();
    };

  }

  frame 1 {
    function BounceBlockObject() {
      this.name = 'bounce block';
      this.xw = tiles.xw * 0.8;
      this.yw = tiles.yw * 0.8;
      this.pos = new Vector2(10, 20);
      this.oldpos = new Vector2(30, 40);
      this.anchor = new Vector2(50, 60);
      this.stiff = 0.05;
      this.mass = 0.2;
      this.ASLEEP = true;
      this.sleepThreshold = 40;
      this.sleepTimer = 0;
      this.touchingObj = null;
      objects.Register(this);
      this.mc = gfx.CreateSprite('debugBounceBlockMC', LAYER_OBJECTS);
      this.mc._visible = false;
    }

    BounceBlockObject.prototype.Destruct = function () {
      gfx.DestroyMC(this.mc);
      delete this.mc;
    };

    BounceBlockObject.prototype.Init = function (params) {
      if (params.length != 2) {
      } else {
        this.anchor.x = params[0];
        this.oldpos.x = this.anchor.x;
        this.pos.x = this.anchor.x;
        this.anchor.y = params[1];
        this.oldpos.y = this.anchor.y;
        this.pos.y = this.anchor.y;
        this.mc._xscale = 2 * this.xw;
        this.mc._yscale = 2 * this.yw;
        this.Draw();
        this.mc._visible = true;
        objects.AddToGrid(this);
        objects.Moved(this);
      }
    };

    BounceBlockObject.prototype.UnInit = function () {
      objects.RemoveFromGrid(this);
      objects.EndDraw(this);
      objects.EndUpdate(this);
      objects.EndThink(this);
    };

    BounceBlockObject.prototype.DumpInitData = function () {
      var v2 = '' + this.anchor.x + OBJPARAM_SEPERATION_CHAR + this.anchor.y;
      return v2;
    };

    BounceBlockObject.prototype.IdleAfterDeath = function () {};

    BounceBlockObject.prototype.Draw = function () {
      this.mc._x = this.pos.x;
      this.mc._y = this.pos.y;
    };

    BounceBlockObject.prototype.TestVsRagParticle = function (rp) {
      var v7 = rp.pos;
      var v5 = v7.y - this.pos.y;
      var v2 = this.yw + rp.yw - Math.abs(v5);
      if (0 < v2) {
        var v6 = v7.x - this.pos.x;
        var v3 = this.xw + rp.xw - Math.abs(v6);
        if (0 < v3) {
          if (v2 < v3) {
            if (v5 <= 0) {
              var v8 = -1;
              v2 *= -1;
            } else {
              var v8 = 1;
            }
            this.pos.y -= (1 - this.mass) * v2;
            rp.ReportCollisionVsObject(0, this.mass * v2, 0, v8, 0.3);
          } else {
            if (v6 < 0) {
              v3 *= -1;
              var v9 = -1;
            } else {
              var v9 = 1;
            }
            this.pos.x -= (1 - this.mass) * v3;
            rp.ReportCollisionVsObject(this.mass * v3, 0, v9, 0, 0.3);
          }
          this.sleepTimer = 0;
          if (this.ASLEEP) {
            this.Wake();
          }
          this.touchingObj = guy;
          return undefined;
        }
      }
      this.touchingOBj = null;
    };

    BounceBlockObject.prototype.TestVsPlayer = function (guy) {
      var v7 = guy.pos;
      var v5 = v7.y - this.pos.y;
      var v2 = this.yw + guy.yw - Math.abs(v5);
      if (0 < v2) {
        var v6 = v7.x - this.pos.x;
        var v3 = this.xw + guy.xw - Math.abs(v6);
        if (0 < v3) {
          if (v2 < v3) {
            if (v5 < 0) {
              var v8 = -1;
              v2 *= -1;
            } else {
              var v8 = 1;
            }
            this.pos.y -= (1 - this.mass) * v2;
            guy.ReportCollisionVsObject(0, this.mass * v2, 0, v8, this);
          } else {
            if (v6 < 0) {
              v3 *= -1;
              var v9 = -1;
            } else {
              var v9 = 1;
            }
            this.pos.x -= (1 - this.mass) * v3;
            guy.ReportCollisionVsObject(this.mass * v3, 0, v9, 0, this);
          }
          this.sleepTimer = 0;
          if (this.ASLEEP) {
            this.Wake();
          }
          this.touchingObj = guy;
          return undefined;
        }
      }
      this.touchingOBj = null;
    };

    BounceBlockObject.prototype.Wake = function () {
      objects.StartUpdate(this);
      objects.StartThink(this);
      objects.StartDraw(this);
      this.ASLEEP = false;
    };

    BounceBlockObject.prototype.Sleep = function () {
      objects.EndUpdate(this);
      objects.EndThink(this);
      objects.EndDraw(this);
      this.ASLEEP = true;
      this.oldpos.x = this.pos.x;
      this.oldpos.y = this.pos.y;
    };

    BounceBlockObject.prototype.Think = function () {
      if (this.sleepThreshold < this.sleepTimer) {
        this.Sleep();
      }
    };

    BounceBlockObject.prototype.Update = function () {
      var v2 = this.pos;
      var v3 = this.oldpos;
      var v9;
      var v8;
      var v7;
      var v6;
      v9 = v3.x;
      v8 = v3.y;
      v3.x = v2.x;
      v7 = v3.x;
      v3.y = v2.y;
      v6 = v3.y;
      v2.x += 0.99 * (v7 - v9);
      v2.y += 0.99 * (v6 - v8);
      var v5 = this.anchor.x - v2.x;
      var v4 = this.anchor.y - v2.y;
      if (0 < v5 * v5 + v4 * v4) {
        v2.x += v5 * this.stiff;
        v2.y += v4 * this.stiff;
        if (this.touchingObj != null) {
        }
      } else {}
      ++this.sleepTimer;
    };

  }

  frame 1 {
    function LaunchPadObject() {
      this.name = 'launch pad';
      this.pos = new Vector2(54, 23);
      this.nx = 0;
      this.ny = 1;
      this.r = tiles.xw * 0.5;
      this.strength = tiles.xw * 0.4285714285714286;
      objects.Register(this);
      this.mc = gfx.CreateSprite('debugLaunchPadMC', LAYER_WALLS);
      this.mc._visible = false;
    }

    LaunchPadObject.prototype.Destruct = function () {
      gfx.DestroyMC(this.mc);
      delete this.mc;
    };

    LaunchPadObject.prototype.Init = function (params) {
      if (params.length != 4) {
      } else {
        this.pos.x = params[0];
        this.pos.y = params[1];
        this.nx = params[2];
        this.ny = params[3];
        this.mc._yscale = 2.5 * this.r;
        this.mc._xscale = this.mc._yscale;
        this.mc._x = this.pos.x;
        this.mc._y = this.pos.y;
        this.mc._visible = true;
        this.mc.gotoAndStop('launch_idle');
        if (this.nx < 0) {
          if (this.ny < 0) {
            this.mc._rotation = -45;
          } else {
            if (0 < this.ny) {
              this.mc._rotation = -135;
            } else {
              this.mc._rotation = -90;
            }
          }
        } else {
          if (0 < this.nx) {
            if (this.ny < 0) {
              this.mc._rotation = 45;
            } else {
              if (0 < this.ny) {
                this.mc._rotation = 135;
              } else {
                this.mc._rotation = 90;
              }
            }
          } else {
            if (this.ny < 0) {
              this.mc._rotation = 0;
            } else {
              if (0 < this.ny) {
                this.mc._rotation = 180;
              } else {}
            }
          }
        }
        objects.AddToGrid(this);
        objects.Moved(this);
      }
    };

    LaunchPadObject.prototype.UnInit = function () {
      objects.RemoveFromGrid(this);
    };

    LaunchPadObject.prototype.DumpInitData = function () {
      var v2 = '' + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y + OBJPARAM_SEPERATION_CHAR + this.nx + OBJPARAM_SEPERATION_CHAR + this.ny;
      return v2;
    };

    LaunchPadObject.prototype.IdleAfterDeath = function () {};

    LaunchPadObject.prototype.TestVsPlayer = function (guy) {
      var v6 = guy.pos;
      var v5 = this.pos.x - guy.pos.x;
      var v4 = this.pos.y - guy.pos.y;
      var v2 = guy.r;
      if (Math.sqrt(v5 * v5 + v4 * v4) < this.r + v2) {
        var v9 = this.pos.x - (v6.x - this.nx * v2);
        var v8 = this.pos.y - (v6.y - this.ny * v2);
        var v10 = v9 * this.nx + v8 * this.ny;
        if (0 <= v10) {
          var v7 = 1;
          if (this.ny < 0) {
            v7 += Math.abs(this.ny);
          }
          this.mc.gotoAndPlay('launch_triggered');
          guy.Launch(this.nx * this.strength, this.ny * this.strength * v7);
        }
      }
    };

    LaunchPadObject.prototype.TestVsRagParticle = function (guy) {
      var v6 = guy.pos;
      var v4 = this.pos.x - guy.pos.x;
      var v3 = this.pos.y - guy.pos.y;
      var v5 = guy.xw;
      if (Math.sqrt(v4 * v4 + v3 * v3) < this.r + v5) {
        this.mc.gotoAndPlay('launch_triggered');
        guy.ReportCollisionVsObject(this.nx * 12, this.ny * 12, 1, 0, 1);
      }
    };

  }

  frame 1 {
    function TestDoorObject() {
      this.name = 'door';
      this.vert = 0;
      this.doorI = 2;
      this.doorJ = 3;
      this.doorpos = new Vector2(29, 19);
      this.doorsize = 10;
      this.doorcell_N = 0;
      this.doorcell_P = 0;
      this.pos = new Vector2(32, 84);
      this.r = tiles.xw * 0.8333333333333334;
      this.deltaI = 0;
      this.deltaJ = 0;
      this.isOpen = false;
      this.doortimer = 0;
      this.maxtimer = 5;
      this.isLocked = false;
      this.isTrap = false;
      this.openStateFront = EID_OFF;
      this.openStateBack = EID_OFF;
      objects.Register(this);
      this.mc = gfx.CreateSprite('debugTestDoorMC', LAYER_WALLS);
      this.mc._visible = false;
      this.mc.gotoAndStop('closed_Trek');
      this.trigMC = gfx.CreateSprite('debugDoorTriggerMC', LAYER_WALLS);
      this.trigMC.gotoAndStop('exit_closed');
      this.trigMC._visible = false;
    }

    TestDoorObject.prototype.Destruct = function () {
      gfx.DestroyMC(this.mc);
      delete this.mc;
      gfx.DestroyMC(this.trigMC);
      delete this.trigMC;
    };

    TestDoorObject.prototype.Init = function (params) {
      if (params.length != 9) {
      } else {
        this.deltaI = params[7];
        this.deltaJ = params[8];
        this.doorI = params[4] + this.deltaI;
        this.doorJ = params[5] + this.deltaJ;
        this.vert = params[2];
        this.isTrap = Boolean(params[3]);
        this.isLocked = Boolean(params[6]);
        this.doorcell_N = tiles.GetTile_I(this.doorI, this.doorJ);
        this.doorpos.x = this.doorcell_N.pos.x;
        this.doorpos.y = this.doorcell_N.pos.y;
        if (this.vert == 1) {
          this.doorpos.y += this.doorcell_N.yw;
          this.doorsize = this.doorcell_N.xw;
          this.doorcell_P = this.doorcell_N.nD;
          this.openStateFront = this.doorcell_N.eD;
          this.openStateBack = this.doorcell_P.eU;
        } else {
          this.doorpos.x += this.doorcell_N.xw;
          this.doorsize = this.doorcell_N.yw;
          this.doorcell_P = this.doorcell_N.nR;
          this.openStateFront = this.doorcell_N.eR;
          this.openStateBack = this.doorcell_P.eL;
        }
        if (this.isLocked) {
          this.openFrameLabel = 'opening_Lock';
          this.closedFrameLabel = 'closed_Lock';
          this.mc.gotoAndStop('closed_Lock');
          this.pos.x = params[0];
          this.pos.y = params[1];
          this.r = tiles.xw * 0.4166666666666667;
          this.isTrap = false;
          this.isOpen = false;
          this.isLocked = true;
          this.trigMC._x = this.pos.x;
          this.trigMC._y = this.pos.y;
          this.trigMC._yscale = this.r * 1.5;
          this.trigMC._xscale = this.trigMC._yscale;
          this.trigMC.gotoAndStop('exit_closed');
          this.trigMC._visible = true;
        } else {
          if (this.isTrap) {
            this.openFrameLabel = 'open_Trap';
            this.closedFrameLabel = 'closing_Trap';
            this.mc.gotoAndStop('open_Trap');
            this.pos.x = params[0];
            this.pos.y = params[1];
            this.r = tiles.xw * 0.4166666666666667;
            this.isOpen = true;
            this.isLocked = false;
            this.isTrap = true;
            this.trigMC._x = this.pos.x;
            this.trigMC._y = this.pos.y;
            this.trigMC._yscale = this.r * 1;
            this.trigMC._xscale = this.trigMC._yscale;
            this.trigMC.gotoAndStop('exit_closed');
            this.trigMC._visible = true;
          } else {
            this.openFrameLabel = 'opening_Trek';
            this.closedFrameLabel = 'closing_Trek';
            this.pos.x = this.doorpos.x;
            this.pos.y = this.doorpos.y;
            this.r = tiles.xw * 0.8333333333333334;
            this.isOpen = false;
            this.isLocked = false;
            this.isTrap = false;
            this.mc.gotoAndStop('closed_Trek');
          }
        }
        objects.AddToGrid(this);
        objects.Moved(this);
        this.mc._yscale = 2 * this.doorcell_N.yw;
        this.mc._xscale = this.mc._yscale;
        this.mc._x = this.doorcell_N.pos.x;
        this.mc._y = this.doorcell_N.pos.y;
        if (this.vert == 1) {
          if (this.deltaJ == 0) {
            this.mc._rotation = 90;
            this.mc._y -= 1;
          } else {
            this.mc._y += this.doorcell_N.yw * 2;
            this.mc._rotation = 270;
          }
        } else {
          if (this.deltaI == 0) {
            this.mc._rotation = 0;
            this.mc._x -= 1;
          } else {
            this.mc._x += this.doorcell_N.xw * 2;
            this.mc._rotation = 180;
          }
        }
        this.mc._visible = true;
        this.UpdateEdges();
      }
    };

    TestDoorObject.prototype.UnInit = function () {
      if (this.vert == 0) {
        this.doorcell_N.eR = this.openStateFront;
        this.doorcell_P.eL = this.openStateBack;
      } else {
        this.doorcell_N.eD = this.openStateFront;
        this.doorcell_P.eU = this.openStateBack;
      }
      objects.RemoveFromGrid(this);
      objects.EndUpdate(this);
    };

    TestDoorObject.prototype.DumpInitData = function () {
      var v2 = '' + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y + OBJPARAM_SEPERATION_CHAR + this.vert + OBJPARAM_SEPERATION_CHAR + Number(this.isTrap) + OBJPARAM_SEPERATION_CHAR + (this.doorI - this.deltaI) + OBJPARAM_SEPERATION_CHAR + (this.doorJ - this.deltaJ) + OBJPARAM_SEPERATION_CHAR + Number(this.isLocked) + OBJPARAM_SEPERATION_CHAR + this.deltaI + OBJPARAM_SEPERATION_CHAR + this.deltaJ;
      return v2;
    };

    TestDoorObject.prototype.UpdateEdges = function () {
      if (this.vert == 0) {
        if (this.isOpen) {
          this.doorcell_N.eR = this.openStateFront;
          this.doorcell_P.eL = this.openStateBack;
        } else {
          this.doorcell_N.eR = EID_SOLID;
          this.doorcell_P.eL = EID_SOLID;
        }
      } else {
        if (this.isOpen) {
          this.doorcell_N.eD = this.openStateFront;
          this.doorcell_P.eU = this.openStateBack;
        } else {
          this.doorcell_N.eD = EID_SOLID;
          this.doorcell_P.eU = EID_SOLID;
        }
      }
    };

    TestDoorObject.prototype.Draw = function () {
      if (this.isOpen) {
        this.mc.gotoAndPlay(this.openFrameLabel);
        this.trigMC.gotoAndStop('exit_open');
      } else {
        this.mc.gotoAndPlay(this.closedFrameLabel);
        this.trigMC.gotoAndStop('exit_closed');
      }
    };

    TestDoorObject.prototype.IdleAfterDeath = function () {
      objects.RemoveFromGrid(this);
    };

    TestDoorObject.prototype.TestVsPlayer = function (guy) {
      var v5 = guy.pos;
      var v3 = this.pos.x - guy.pos.x;
      var v2 = this.pos.y - guy.pos.y;
      if (Math.sqrt(v3 * v3 + v2 * v2) < this.r + guy.r) {
        this.doortimer = 0;
        if (this.isTrap) {
          this.Close();
          objects.RemoveFromGrid(this);
          this.TestVsPlayer = null;
        } else {
          if (!this.isOpen) {
            this.Open();
          }
        }
      }
    };

    TestDoorObject.prototype.Open = function () {
      this.isOpen = true;
      this.UpdateEdges();
      this.Draw();
      if (!this.isTrap && !this.isLocked) {
        objects.StartUpdate(this);
      }
    };

    TestDoorObject.prototype.Close = function () {
      objects.EndUpdate(this);
      this.isOpen = false;
      this.UpdateEdges();
      this.Draw();
    };

    TestDoorObject.prototype.Update = function () {
      ++this.doortimer;
      if (this.maxtimer < this.doortimer) {
        this.Close();
      }
    };

  }

  frame 1 {
    function OneWayPlatformObject() {
      this.name = 'oneway block';
      this.xw = tiles.xw;
      this.yw = tiles.xw;
      this.pos = new Vector2(10, 20);
      this.dir = new Vector2(0, 1);
      this.dirEnum = AI_DIR_U;
      objects.Register(this);
      this.mc = gfx.CreateSprite('debugOneWayPlatformMC', LAYER_WALLS);
      this.mc._visible = false;
    }

    OneWayPlatformObject.prototype.Destruct = function () {
      gfx.DestroyMC(this.mc);
      delete this.mc;
    };

    OneWayPlatformObject.prototype.Init = function (params) {
      if (params.length != 3) {
      } else {
        this.pos.x = params[0];
        this.pos.y = params[1];
        var v2 = params[2];
        this.dirEnum = v2;
        if (v2 == AI_DIR_U) {
          this.dir.x = 0;
          this.dir.y = -1;
        } else {
          if (v2 == AI_DIR_D) {
            this.dir.x = 0;
            this.dir.y = 1;
            this.mc._rotation = 180;
          } else {
            if (v2 == AI_DIR_L) {
              this.dir.x = -1;
              this.dir.y = 0;
              this.mc._rotation = -90;
            } else {
              if (v2 == AI_DIR_R) {
                this.dir.x = 1;
                this.dir.y = 0;
                this.mc._rotation = 90;
              } else {}
            }
          }
        }
        this.mc._x = this.pos.x;
        this.mc._y = this.pos.y;
        this.mc._xscale = 2 * this.xw;
        this.mc._yscale = 2 * this.yw;
        this.mc._visible = true;
        objects.AddToGrid(this);
        objects.Moved(this);
      }
    };

    OneWayPlatformObject.prototype.UnInit = function () {
      objects.RemoveFromGrid(this);
    };

    OneWayPlatformObject.prototype.DumpInitData = function () {
      var v2 = '' + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y + OBJPARAM_SEPERATION_CHAR + this.dirEnum;
      return v2;
    };

    OneWayPlatformObject.prototype.IdleAfterDeath = function () {};

    OneWayPlatformObject.prototype.TestVsPlayer = function (guy) {
      var v3 = guy.pos;
      var v7 = v3.y - this.pos.y;
      var v9 = this.yw + guy.yw - Math.abs(v7);
      if (0 < v9) {
        var v8 = v3.x - this.pos.x;
        var v10 = this.xw + guy.xw - Math.abs(v8);
        if (0 < v10) {
          if (this.dir.x == 0) {
            var v4 = guy.pos.y - guy.oldpos.y;
            if (v4 * this.dir.y <= 0) {
              var v11 = guy.oldpos.y - this.dir.y * guy.yw - (this.pos.y + this.dir.y * this.yw);
              if (0 <= v11 * this.dir.y) {
                var v5 = this.pos.y + this.dir.y * this.yw - (guy.pos.y - this.dir.y * guy.yw);
                guy.ReportCollisionVsObject(0, v5, 0, this.dir.y, this);
              }
            }
          } else {
            var v4 = guy.pos.x - guy.oldpos.x;
            if (v4 * this.dir.x <= 0) {
              var v11 = guy.oldpos.x - this.dir.x * guy.xw - (this.pos.x + this.dir.x * this.xw);
              if (0 <= v11 * this.dir.x) {
                var v6 = this.pos.x + this.dir.x * this.xw - (guy.pos.x - this.dir.x * guy.xw);
                guy.ReportCollisionVsObject(v6, 0, this.dir.x, 0, this);
              }
            }
          }
        }
      }
    };

    OneWayPlatformObject.prototype.TestVsRagParticle = function (guy) {
      var v3 = guy.pos;
      var v7 = v3.y - this.pos.y;
      var v9 = this.yw + guy.yw - Math.abs(v7);
      if (0 < v9) {
        var v8 = v3.x - this.pos.x;
        var v10 = this.xw + guy.xw - Math.abs(v8);
        if (0 < v10) {
          if (this.dir.x == 0) {
            var v4 = guy.pos.y - guy.oldpos.y;
            if (v4 * this.dir.y <= 0) {
              var v11 = guy.oldpos.y - this.dir.y * guy.yw - (this.pos.y + this.dir.y * this.yw);
              if (0 <= v11 * this.dir.y) {
                var v5 = this.pos.y + this.dir.y * this.yw - (guy.pos.y - this.dir.y * guy.yw);
                guy.ReportCollisionVsObject(0, v5, 0, this.dir.y, 0.3);
              }
            }
          } else {
            var v4 = guy.pos.x - guy.oldpos.x;
            if (v4 * this.dir.x <= 0) {
              var v11 = guy.oldpos.x - this.dir.x * guy.xw - (this.pos.x + this.dir.x * this.xw);
              if (0 <= v11 * this.dir.x) {
                var v6 = this.pos.x + this.dir.x * this.xw - (guy.pos.x - this.dir.x * guy.xw);
                guy.ReportCollisionVsObject(v6, 0, this.dir.x, 0, 0.3);
              }
            }
          }
        }
      }
    };

  }

  frame 1 {
    function ThwompObject() {
      this.name = 'thwump';
      this.pos = new Vector2(141, 14);
      this.anchor = new Vector2(91, 82);
      this.fallgoal = new Vector2(98, 74);
      this.goal = this.fallgoal;
      this.i = 6;
      this.j = 7;
      this.mini = 2;
      this.minj = 5;
      this.maxi = 8;
      this.maxj = 3;
      this.xw = tiles.xw * 0.75;
      this.yw = tiles.xw * 0.75;
      this.movedir = 1;
      this.fallspeed = tiles.xw * 0.3571428571428572;
      this.raisespeed = tiles.xw * 0.1428571428571429;
      this.speed = this.fallspeed;
      this.playerWasStanding = false;
      this.isMoving = false;
      this.dirEnum = AI_DIR_U;
      this.dir = new Vector2(1, 0);
      objects.Register(this);
      this.mc = gfx.CreateSprite('debugThwompMC', LAYER_OBJECTS);
      this.mc._visible = false;
    }

    ThwompObject.prototype.Destruct = function () {
      gfx.DestroyMC(this.mc);
      delete this.mc;
    };

    ThwompObject.prototype.Init = function (params) {
      if (params.length != 3) {
      } else {
        this.pos.x = params[0];
        this.pos.y = params[1];
        this.anchor.x = this.pos.x;
        this.anchor.y = this.pos.y;
        objects.AddToGrid(this);
        objects.StartUpdate(this);
        objects.Moved(this);
        this.i = this.cell.i;
        this.j = this.cell.j;
        var v4 = params[2];
        var v9 = 0;
        this.dirEnum = v4;
        if (v4 == AI_DIR_U) {
          this.dir.x = 0;
          this.dir.y = -1;
          var v3 = this.pos.x;
          var v6 = this.pos.y;
          var v2 = this.cell.nU;
          while (v2.ID == TID_EMPTY) {
            v6 -= 2 * this.cell.yw;
            v2 = v2.nU;
          }
          v6 -= this.yw;
          v6 -= this.pos.y - this.cell.pos.y;
          this.mc._rotation = 180;
        } else {
          if (v4 == AI_DIR_D) {
            this.dir.x = 0;
            this.dir.y = 1;
            var v3 = this.pos.x;
            var v6 = this.pos.y;
            var v2 = this.cell.nD;
            while (v2.ID == TID_EMPTY) {
              v6 += 2 * this.cell.yw;
              v2 = v2.nD;
            }
            v6 += this.yw;
            v6 -= this.pos.y - this.cell.pos.y;
            this.mc._rotation = 0;
          } else {
            if (v4 == AI_DIR_L) {
              this.dir.x = -1;
              this.dir.y = 0;
              var v3 = this.pos.x;
              var v6 = this.pos.y;
              var v2 = this.cell.nL;
              while (v2.ID == TID_EMPTY) {
                v3 -= 2 * this.cell.xw;
                v2 = v2.nL;
              }
              v3 -= this.xw;
              v3 -= this.pos.x - this.cell.pos.x;
              this.mc._rotation = 90;
            } else {
              if (v4 == AI_DIR_R) {
                this.dir.x = 1;
                this.dir.y = 0;
                var v3 = this.pos.x;
                var v6 = this.pos.y;
                var v2 = this.cell.nR;
                while (v2.ID == TID_EMPTY) {
                  v3 += 2 * this.cell.xw;
                  v2 = v2.nR;
                }
                v3 += this.xw;
                v3 -= this.pos.x - this.cell.pos.x;
                this.mc._rotation = -90;
              } else {}
            }
          }
        }
        this.fallgoal.x = storedv3;
        this.fallgoal.y = storedv6;
        this.goal = this.fallgoal;
        this.i = this.cell.i;
        this.j = this.cell.j;
        this.mini = this.cell.i;
        this.minj = this.cell.j;
        var v7 = tiles.GetTile_S(storedv3, storedv6);
        this.maxi = v7.i;
        this.maxj = v7.j;
        if (this.dir.x < 0) {
          var v8 = this.mini;
          this.mini = this.maxi;
          this.maxi = v8;
        }
        if (this.dir.y < 0) {
          v8 = this.minj;
          this.minj = this.maxj;
          this.maxj = v8;
        }
        this.Update = this.Update_Waiting;
        this.mc._xscale = 2 * this.xw;
        this.mc._yscale = 2 * this.yw;
        this.Draw();
        this.mc._visible = true;
      }
    };

    ThwompObject.prototype.UnInit = function () {
      objects.RemoveFromGrid(this);
      objects.EndUpdate(this);
      objects.EndDraw(this);
    };

    ThwompObject.prototype.DumpInitData = function () {
      var v2 = '' + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y + OBJPARAM_SEPERATION_CHAR + this.dirEnum;
      return v2;
    };

    ThwompObject.prototype.IdleAfterDeath = function () {
      if (this.isMoving) {
        this.Update_Waiting = this.Update_Idle;
      } else {
        this.Update = this.Update_Idle;
      }
    };

    ThwompObject.prototype.Update_Idle = function () {};

    ThwompObject.prototype.Draw = function () {
      this.mc._x = this.pos.x;
      this.mc._y = this.pos.y;
    };

    ThwompObject.prototype.TestVsPlayer = function (guy) {
      var v7 = guy.pos;
      var v5 = v7.y - this.pos.y;
      var v8 = Math.abs(v5);
      var v3 = this.yw + guy.yw - v8;
      if (0 < v3) {
        var v6 = v7.x - this.pos.x;
        var v9 = Math.abs(v6);
        var v4 = this.xw + guy.xw - v9;
        if (0 < v4) {
          if (v3 < v4) {
            if (v5 < 0) {
              if (this.dir.y < 0) {
                particles.SpawnZapThwompV(this.pos, this.xw, -this.yw, guy.pos);
                game.KillPlayer(KILLTYPE_ELECTRIC, 0, -8, guy.pos.x, guy.pos.y - 0.5 * guy.r, this);
              } else {
                guy.ReportCollisionVsObject(0, -v3, 0, -1, this);
              }
            } else {
              if (0 < this.dir.y) {
                particles.SpawnZapThwompV(this.pos, this.xw, this.yw, guy.pos);
                game.KillPlayer(KILLTYPE_ELECTRIC, 0, 6, guy.pos.x, guy.pos.y + 0.5 * guy.r, this);
              } else {
                guy.ReportCollisionVsObject(0, v3, 0, 1, this);
              }
            }
          } else {
            if (v6 < 0) {
              if (this.dir.x < 0) {
                particles.SpawnZapThwompH(this.pos, -this.xw, this.yw, guy.pos);
                game.KillPlayer(KILLTYPE_ELECTRIC, -8, -4, guy.pos.x - 0.5 * guy.r, guy.pos.y, this);
              } else {
                guy.ReportCollisionVsObject(-v4, 0, -1, 0, this);
              }
            } else {
              if (0 < this.dir.x) {
                particles.SpawnZapThwompH(this.pos, this.xw, this.yw, guy.pos);
                game.KillPlayer(KILLTYPE_ELECTRIC, 8, -4, guy.pos.x + 0.5 * guy.r, guy.pos.y, this);
              } else {
                guy.ReportCollisionVsObject(v4, 0, 1, 0, this);
              }
            }
          }
        }
      }
    };

    ThwompObject.prototype.TestVsRagParticle = function (guy) {
      var v7 = guy.pos;
      var v5 = v7.y - this.pos.y;
      var v8 = Math.abs(v5);
      var v3 = this.yw + guy.yw - v8;
      if (0 < v3) {
        var v6 = v7.x - this.pos.x;
        var v9 = Math.abs(v6);
        var v4 = this.xw + guy.xw - v9;
        if (0 < v4) {
          if (v3 < v4) {
            if (v5 < 0) {
              if (this.dir.y < 0) {
                particles.SpawnZapThwompV(this.pos, this.xw, -this.yw, guy.pos);
                guy.ReportCollisionVsObject(0, -8, 0, -1, 1);
                player.RagDie(KILLTYPE_ELECTRIC);
              } else {
                guy.ReportCollisionVsObject(0, -v3, 0, -1, 0.3);
              }
            } else {
              if (0 < this.dir.y) {
                particles.SpawnZapThwompV(this.pos, this.xw, this.yw, guy.pos);
                guy.ReportCollisionVsObject(0, 6, 0, 1, 1);
                player.RagDie(KILLTYPE_ELECTRIC);
              } else {
                guy.ReportCollisionVsObject(0, v3, 0, 1, 0.3);
              }
            }
          } else {
            if (v6 < 0) {
              if (this.dir.x < 0) {
                particles.SpawnZapThwompH(this.pos, -this.xw, this.yw, guy.pos);
                guy.ReportCollisionVsObject(-8, -4, -1, 0, 1);
                player.RagDie(KILLTYPE_ELECTRIC);
              } else {
                guy.ReportCollisionVsObject(-v4, 0, -1, 0, 0.3);
              }
            } else {
              if (0 < this.dir.x) {
                particles.SpawnZapThwompH(this.pos, this.xw, this.yw, guy.pos);
                guy.ReportCollisionVsObject(8, -4, 1, 0, 1);
                player.RagDie(KILLTYPE_ELECTRIC);
              } else {
                guy.ReportCollisionVsObject(v4, 0, 1, 0, 0.3);
              }
            }
          }
        }
      }
    };

    ThwompObject.prototype.StartFall = function () {
      this.isMoving = true;
      this.speed = this.fallspeed;
      this.movedir = 1;
      this.goal = this.fallgoal;
      this.Update = this.Update_Moving;
      objects.StartDraw(this);
    };

    ThwompObject.prototype.StartRaise = function () {
      this.isMoving = true;
      this.speed = this.raisespeed;
      this.movedir = -1;
      this.goal = this.anchor;
      this.Update = this.Update_Moving;
    };

    ThwompObject.prototype.StartWait = function () {
      this.isMoving = false;
      this.Update = this.Update_Waiting;
      objects.EndDraw(this);
    };

    ThwompObject.prototype.Update_Waiting = function () {
      if (this.dir.x == 0) {
        if (Math.abs(this.pos.x - player.pos.x) < 2 * (this.xw + player.xw)) {
          var v2 = player.cell.j;
          if (this.maxj < v2 || v2 < this.minj) {
          } else {
            this.StartFall();
          }
        }
      } else {
        if (Math.abs(this.pos.y - player.pos.y) < 2 * (this.yw + player.yw)) {
          var v2 = player.cell.i;
          if (this.maxi < v2 || v2 < this.mini) {
          } else {
            this.StartFall();
          }
        }
      }
    };

    ThwompObject.prototype.Update_Moving = function () {
      var v3 = this.goal.x - this.pos.x;
      var v2 = this.goal.y - this.pos.y;
      var v4 = v3 * v3 + v2 * v2;
      if (v4 < this.speed * this.speed) {
        this.pos.x = this.goal.x;
        this.pos.y = this.goal.y;
        if (this.movedir == 1) {
          this.StartRaise();
        } else {
          this.StartWait();
        }
      } else {
        this.pos.x += this.movedir * this.dir.x * this.speed;
        this.pos.y += this.movedir * this.dir.y * this.speed;
      }
      objects.Moved(this);
    };

  }

  frame 1 {
    function HomingLauncherObject() {
      this.name = 'homing rocket';
      this.basepos = new Vector2(3, 8);
      this.view = new Vector2(4, 56);
      this.pos = new Vector2(0, 9);
      this.mdir = new Vector2(7, 6);
      this.speed = 0;
      this.maxspeed = tiles.xw * 0.2857142857142857;
      this.startaccel = 0.1;
      this.curaccel = this.startaccel;
      this.accelrate = 1.1;
      this.turnrate = 0.1;
      this.isHoming = false;
      this.prefireDelay = 10;
      this.fireDelayTimer = 0;
      objects.Register(this);
      this.mc = gfx.CreateSprite('debugHomingLauncherMC', LAYER_WALLS);
      this.rocketmc = gfx.CreateSprite('debugHomingRocketMC', LAYER_OBJECTS);
      this.mc._visible = false;
      this.rocketmc._visible = true;
      this.mc.gotoAndStop('rocket_waiting');
      this.snd = new Sound(this.mc);
    }

    HomingLauncherObject.prototype.Destruct = function () {
      gfx.DestroyMC(this.mc);
      delete this.mc;
      gfx.DestroyMC(this.rocketmc);
      delete this.rocketmc;
      delete this.snd;
    };

    HomingLauncherObject.prototype.Init = function (params) {
      if (params.length != 2) {
      } else {
        this.basepos.x = params[0];
        this.basepos.y = params[1];
        this.StartIdle();
        this.mc._yscale = tiles.xw;
        this.mc._xscale = this.mc._yscale;
        this.mc._x = this.basepos.x;
        this.mc._y = this.basepos.y;
        this.mc._visible = true;
        this.mc.gotoAndStop('rocket_waiting');
        this.rocketmc._yscale = 100;
        this.rocketmc._xscale = 100;
        this.rocketmc._x = this.basepos.x;
        this.rocketmc._y = this.basepos.y;
        this.rocketmc._visible = false;
      }
    };

    HomingLauncherObject.prototype.UnInit = function () {
      objects.RemoveFromGrid(this);
      objects.EndUpdate(this);
      objects.EndThink(this);
    };

    HomingLauncherObject.prototype.DumpInitData = function () {
      var v2 = '' + this.basepos.x + OBJPARAM_SEPERATION_CHAR + this.basepos.y;
      return v2;
    };

    HomingLauncherObject.prototype.IdleAfterDeath = function () {
      if (this.isHoming) {
        this.StartIdle = this.StartIdle_Death;
      } else {
        objects.EndThink(this);
      }
    };

    HomingLauncherObject.prototype.StartIdle_Death = function () {
      this.isHoming = false;
    };

    HomingLauncherObject.prototype.Draw = function () {
      this.rocketmc._x = this.pos.x;
      this.rocketmc._y = this.pos.y;
      var v2 = NormToRot(this.mdir.x, this.mdir.y);
      this.rocketmc._rotation = v2;
      particles.SpawnRocketSmoke(this.pos, v2);
    };

    HomingLauncherObject.prototype.StartFiring = function () {
      objects.EndThink(this);
      objects.StartUpdate(this);
      this.isHoming = true;
      this.fireDelayTimer = 0;
      this.Update = this.Update_PreFire;
    };

    HomingLauncherObject.prototype.StartIdle = function () {
      this.isHoming = false;
      objects.StartThink(this);
    };

    HomingLauncherObject.prototype.FireMissile = function () {
      this.curaccel = this.startaccel;
      this.speed = 0;
      this.pos.x = this.basepos.x;
      this.pos.y = this.basepos.y;
      objects.AddToGrid(this);
      objects.StartDraw(this);
      this.Update = this.Update_Homing;
      var v3 = player.pos.x - this.basepos.x;
      var v2 = player.pos.y - this.basepos.y;
      var v4 = Math.sqrt(v3 * v3 + v2 * v2);
      if (v4 == 0) {
      } else {
        v3 /= v4;
        v2 /= v4;
        this.mdir.x = v3;
        this.mdir.y = v2;
      }
      this.rocketmc._visible = true;
      this.mc.gotoAndPlay('rocket_fire');
    };

    HomingLauncherObject.prototype.ExplodeMissile = function () {
      this.snd.stop();
      this.rocketmc._visible = false;
      this.mc.gotoAndPlay('rocket_explode');
      particles.SpawnExplosion(this.pos);
      objects.EndUpdate(this);
      objects.EndDraw(this);
      objects.RemoveFromGrid(this);
      this.StartIdle();
    };

    HomingLauncherObject.prototype.Think = function () {
      if (QueryRayObj(this.view, this.basepos, player.pos, player)) {
        this.StartFiring();
      }
    };

    HomingLauncherObject.prototype.TestVsPlayer = function (guy) {
      var v3 = guy.pos.x - this.pos.x;
      var v2 = guy.pos.y - this.pos.y;
      var v4 = Math.sqrt(v3 * v3 + v2 * v2);
      if (v4 < player.r) {
        game.KillPlayer(KILLTYPE_EXPLOSIVE, v3, v2, this.pos.x, this.pos.y, this);
        this.ExplodeMissile();
        return undefined;
      }
    };

    HomingLauncherObject.prototype.Update_PreFire = function () {
      ++this.fireDelayTimer;
      if (this.prefireDelay <= this.fireDelayTimer) {
        this.FireMissile();
      }
    };

    HomingLauncherObject.prototype.Update_Homing = function () {
      var v3 = this.pos;
      if (this.speed < this.maxspeed) {
        this.curaccel *= this.accelrate;
        this.speed += this.curaccel;
      } else {
        this.speed = this.maxspeed;
      }
      v3.x += this.speed * this.mdir.x;
      v3.y += this.speed * this.mdir.y;
      if (QueryPointvsTileMap(v3.x, v3.y)) {
        this.ExplodeMissile();
        return undefined;
      } else {
        var v2 = this.cell;
        if (objects.Moved(this)) {
          var v5 = this.cell;
          var v4;
          if (v5 == v2.nR) {
            v4 = v2.eR;
          } else {
            if (v5 == v2.nL) {
              v4 = v2.eL;
            } else {
              if (v5 == v2.nU) {
                v4 = v2.eU;
              } else {
                if (v5 == v2.nD) {
                  v4 = v2.eD;
                } else {
                  v4 = EID_OFF;
                }
              }
            }
          }
          if (v4 == EID_SOLID) {
            this.ExplodeMissile();
            return undefined;
          }
        }
      }
      var v6 = player;
      dx = 2 * v6.pos.x - v6.oldpos.x - (v3.x + this.speed * this.mdir.x);
      dy = 2 * v6.pos.y - v6.oldpos.y - (v3.y + this.speed * this.mdir.y);
      var v7 = Math.sqrt(dx * dx + dy * dy);
      dx /= v7;
      dy /= v7;
      var v11 = this.mdir.x * dx + this.mdir.y * dy;
      var v9 = -this.mdir.y * dx + this.mdir.x * dy;
      var v8 = this.turnrate;
      if (v11 < 0) {
      }
      var v12 = v9 * -this.mdir.y;
      var v10 = v9 * this.mdir.x;
      this.mdir.x += v12 * v8;
      this.mdir.y += v10 * v8;
      v7 = Math.sqrt(this.mdir.x * this.mdir.x + this.mdir.y * this.mdir.y);
      if (v7 == 0) {
        return undefined;
      }
      this.mdir.x /= v7;
      this.mdir.y /= v7;
    };

  }

  frame 1 {
    function TurretObject() {
      this.name = 'gauss turret';
      this.pos = new Vector2(21, 12);
      objects.Register(this);
      this.view = new Vector2(0, 0);
      this.targ = new Vector2(0, 0);
      this.aim = new Vector2(this.pos.x, this.pos.y);
      this.closeAimSpeed = 0.05;
      this.midAimSpeed = 0.035;
      this.farAimSpeed = 0.03;
      this.aimSpeed = this.farAimSpeed;
      this.outerThreshold = tiles.xw * 8;
      this.innerThreshold = tiles.xw * 2;
      this.midThreshold = 0.25 * this.outerThreshold + 0.75 * this.innerThreshold;
      this.outerThreshold *= this.outerThreshold;
      this.midThreshold *= this.midThreshold;
      this.innerThreshold *= this.innerThreshold;
      this.shotRate = 60;
      this.shotTimer = 0;
      this.fireDelayTimer = 0;
      this.prefireDelay = 10;
      this.postfireDelay = 10;
      this.isFiring = false;
      this.mc = gfx.CreateSprite('debugTurretMC', LAYER_WALLS);
      this.mc._visible = false;
      this.crosshairMC = gfx.CreateSprite('debugTurretCrosshairMC', LAYER_OBJECTS);
      this.crosshairMC._visible = false;
    }

    TurretObject.prototype.Destruct = function () {
      gfx.DestroyMC(this.mc);
      delete this.mc;
      gfx.DestroyMC(this.crosshairMC);
      delete this.crosshairMC;
    };

    TurretObject.prototype.Init = function (params) {
      if (params.length != 2) {
      } else {
        this.aim.x = params[0];
        this.pos.x = this.aim.x;
        this.aim.y = params[1];
        this.pos.y = this.aim.y;
        objects.StartThink(this);
        this.Think = this.Think_Waiting;
        this.mc._x = this.pos.x;
        this.mc._y = this.pos.y;
        this.mc._yscale = tiles.xw;
        this.mc._xscale = this.mc._yscale;
        this.mc._visible = true;
        this.mc.gotoAndStop('turret_idle');
        this.crosshairMC._yscale = tiles.xw * 1.5;
        this.crosshairMC._xscale = this.crosshairMC._yscale;
        this.crosshairMC._visible = false;
      }
    };

    TurretObject.prototype.UnInit = function () {
      objects.EndThink(this);
      objects.EndUpdate(this);
      objects.EndDraw(this);
    };

    TurretObject.prototype.DumpInitData = function () {
      var v2 = '' + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y;
      return v2;
    };

    TurretObject.prototype.Draw = function () {
      this.crosshairMC._x = this.aim.x;
      this.crosshairMC._y = this.aim.y;
    };

    TurretObject.prototype.IdleAfterDeath = function () {
      this.StopTargetting();
      objects.EndThink(this);
      objects.EndDraw(this);
    };

    TurretObject.prototype.StartFiring = function () {
      this.crosshairMC.gotoAndStop('prefire');
      this.mc.gotoAndPlay('turret_prefire');
      objects.EndThink(this);
      objects.EndDraw(this);
      this.isFiring = true;
      this.fireDelayTimer = 0;
      this.Update = this.Update_PreFire;
    };

    TurretObject.prototype.StopFiring = function () {
      objects.StartThink(this);
      this.Think = this.Think_Targetting;
      this.crosshairMC.gotoAndStop('postfire');
      this.mc.gotoAndPlay('turret_idle');
      this.isFiring = false;
      this.fireDelayTimer = 0;
      this.Update = this.Update_PostFire;
    };

    TurretObject.prototype.StartTargetting = function () {
      this.crosshairMC._visible = true;
      this.crosshairMC.gotoAndStop('aim_far');
      this.aimSpeed = this.farAimSpeed;
      this.aim.x = this.pos.x;
      this.aim.y = this.pos.y;
      this.KeepTargetting();
    };

    TurretObject.prototype.StopTargetting = function () {
      this.crosshairMC._visible = false;
      objects.EndUpdate(this);
      this.Think = this.Think_Waiting;
      objects.EndDraw(this);
    };

    TurretObject.prototype.KeepTargetting = function () {
      this.shotTimer = this.shotRate;
      this.Update = this.Update_Targetting;
      this.Think = this.Think_Targetting;
      objects.StartUpdate(this);
      objects.StartDraw(this);
    };

    TurretObject.prototype.Fire = function () {
      this.mc.gotoAndPlay('turret_firing');
      if (QueryRayObj(this.targ, this.pos, this.aim, player)) {
        var v3 = this.aim.x - this.pos.x;
        var v2 = this.aim.y - this.pos.y;
        var v4 = Math.sqrt(v3 * v3 + v2 * v2);
        if (v4 == 0) {
          v3 = 1;
          v2 = 1;
        } else {
          v3 /= v4;
          v2 /= v4;
        }
        game.KillPlayer(KILLTYPE_HARDBULLET, v3 * 8, v2 * 8, this.targ.x, this.targ.y, this);
        this.targ.x += v3 * player.r;
        this.targ.y += v2 * player.r;
        var v5 = NormToRot(v3, v2);
      } else {
        var v3 = this.aim.x - this.pos.x;
        var v2 = this.aim.y - this.pos.y;
        var v4 = Math.sqrt(v3 * v3 + v2 * v2);
        if (v4 == 0) {
          v3 = 1;
          v2 = 1;
        } else {
          v3 /= v4;
          v2 /= v4;
        }
        var v5 = NormToRot(-v3, -v2);
      }
      particles.SpawnTurretBullet(this.pos, this.targ, v5);
      this.StopFiring();
    };

    TurretObject.prototype.Think_Waiting = function () {
      if (QueryRayObj(this.view, this.pos, player.pos, player)) {
        this.StartTargetting();
      }
    };

    TurretObject.prototype.Think_Targetting = function () {
      if (!QueryRayObj(this.view, this.pos, player.pos, player)) {
        this.StopTargetting();
      }
    };

    TurretObject.prototype.Update_Targetting = function () {
      var v7 = 2 * player.pos.x - player.oldpos.x;
      var v6 = 2 * player.pos.y - player.oldpos.y;
      var v2 = this.aim;
      var v5 = v2.x - v7;
      var v4 = v2.y - v6;
      v2.x -= this.aimSpeed * v5;
      v2.y -= this.aimSpeed * v4;
      var v3 = v5 * v5 + v4 * v4;
      if (this.outerThreshold < v3) {
        this.crosshairMC.gotoAndStop('aim_far');
        this.aimSpeed = this.farAimSpeed;
        return undefined;
      } else {
        if (v3 < this.innerThreshold) {
          this.shotTimer -= 2 + game.GetTime() % 4;
        } else {
          if (v3 < this.midThreshold) {
            this.crosshairMC.gotoAndStop('aim_near');
            this.aimSpeed = this.closeAimSpeed;
            this.shotTimer -= 1 + game.GetTime() % 2;
          } else {
            this.crosshairMC.gotoAndStop('aim_mid');
            this.aimSpeed = this.midAimSpeed;
            this.shotTimer -= 0.5;
          }
        }
      }
      if (this.shotTimer < 0) {
        this.shotTimer = this.shotRate;
        this.StartFiring();
      }
    };

    TurretObject.prototype.Update_PreFire = function () {
      ++this.fireDelayTimer;
      if (this.prefireDelay <= this.fireDelayTimer) {
        if (!QueryRayObj(this.view, this.pos, player.pos, player)) {
          this.StopFiring();
        } else {
          this.Fire();
        }
      }
    };

    TurretObject.prototype.Update_PostFire = function () {
      ++this.fireDelayTimer;
      this.shotMC._alpha = 100 - 100 * (this.fireDelayTimer / this.postfireDelay);
      if (this.postfireDelay <= this.fireDelayTimer) {
        this.shotMC._visible = false;
        if (!QueryRayObj(this.view, this.pos, player.pos, player)) {
          this.StopTargetting();
        } else {
          this.KeepTargetting();
        }
      }
    };

  }

  frame 1 {
    function MineObject() {
      this.name = 'mine';
      this.pos = new Vector2(43, 16);
      this.r = tiles.xw * 0.3333333333333333;
      objects.Register(this);
      this.mc = gfx.CreateSprite('debugMineMC', LAYER_OBJECTS);
      this.mc._visible = false;
    }

    MineObject.prototype.Destruct = function () {
      gfx.DestroyMC(this.mc);
      delete this.mc;
    };

    MineObject.prototype.Init = function (params) {
      if (params.length != 2) {
      } else {
        this.pos.x = params[0];
        this.pos.y = params[1];
        objects.AddToGrid(this);
        objects.Moved(this);
        this.mc._yscale = 2 * this.r;
        this.mc._xscale = this.mc._yscale;
        this.mc._x = this.pos.x;
        this.mc._y = this.pos.y;
        this.mc.gotoAndStop('mine_unexploded');
        this.mc._visible = true;
      }
    };

    MineObject.prototype.UnInit = function () {
      objects.RemoveFromGrid(this);
    };

    MineObject.prototype.DumpInitData = function () {
      var v2 = '' + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y;
      return v2;
    };

    MineObject.prototype.IdleAfterDeath = function () {};

    MineObject.prototype.TestVsPlayer = function (guy) {
      var v4 = guy.pos;
      var v3 = this.pos.x - v4.x;
      var v2 = this.pos.y - v4.y;
      if (Math.sqrt(v3 * v3 + v2 * v2) < this.r + guy.r) {
        this.Explode(-v3, -v2);
      }
    };

    MineObject.prototype.TestVsRagParticle = function (guy) {
      var v5 = guy.pos;
      var v4 = this.pos.x - v5.x;
      var v3 = this.pos.y - v5.y;
      var v2 = Math.sqrt(v4 * v4 + v3 * v3);
      if (v2 < this.r + guy.xw) {
        player.RagDie(KILLTYPE_EXPLOSIVE);
        guy.ReportCollisionVsObject((-v4 / v2) * 16, (-v3 / v2) * 16, -v4 / v2, -v3 / v2, 1);
        this.ExplodeRag(-v4, -v3);
      }
    };

    MineObject.prototype.Explode = function (dx, dy) {
      game.KillPlayer(KILLTYPE_EXPLOSIVE, dx, dy, this.pos.x, this.pos.y, this);
      particles.SpawnExplosion(this.pos);
      objects.RemoveFromGrid(this);
      this.mc.gotoAndStop('mine_exploded');
    };

    MineObject.prototype.ExplodeRag = function (dx, dy) {
      particles.SpawnExplosion(this.pos);
      objects.RemoveFromGrid(this);
      this.mc.gotoAndStop('mine_exploded');
    };

  }

  frame 1 {
    function FloorGuardObject() {
      this.name = 'floor guard';
      this.pos = new Vector2(41, 14);
      this.r = tiles.xw * 0.5;
      this.dir = 1;
      this.speed = tiles.xw * 0.4285714285714286;
      this.view = new Vector2(0, 0);
      objects.Register(this);
      this.mc = gfx.CreateSprite('debugFloorGuardMC', LAYER_OBJECTS);
      this.mc._visible = false;
      this.mc.gotoAndStop('floorguard_idle');
    }

    FloorGuardObject.prototype.Destruct = function () {
      gfx.DestroyMC(this.mc);
      delete this.mc;
    };

    FloorGuardObject.prototype.Init = function (params) {
      if (params.length != 3) {
      } else {
        this.pos.x = params[0];
        this.pos.y = params[1];
        if (dir < 0) {
          this.dir = -1;
        } else {
          this.dir = 1;
        }
        objects.AddToGrid(this);
        objects.Moved(this);
        objects.StartUpdate(this);
        this.Update = this.Update_Idle;
        this.pos.y = this.cell.pos.y + this.cell.yw - this.r;
        var v2 = this.cell;
        while (!false) {
          v2 = v2.nR;
          if (TID_EMPTY < v2.ID || v2.eD != EID_SOLID) {
            this.maxX = v2.pos.x - v2.xw - this.r;
            break;
          }
        }
        while (!false) {
          v2 = v2.nL;
          if (TID_EMPTY < v2.ID || v2.eD != EID_SOLID) {
            this.minX = v2.pos.x + v2.xw + this.r;
            break;
          }
        }
        v2 = this.cell;
        this.mini = v2.i;
        this.maxi = v2.i;
        while (!false) {
          v2 = v2.nR;
          if (TID_EMPTY < v2.ID) {
            break;
          }
          ++this.maxi;
        }
        v2 = this.cell;
        while (!false) {
          v2 = v2.nL;
          if (TID_EMPTY < v2.ID) {
            break;
          }
          --this.mini;
        }
        this.mc._yscale = 2 * this.r;
        this.mc._xscale = this.mc._yscale;
        this.Draw();
        this.mc._visible = true;
      }
    };

    FloorGuardObject.prototype.UnInit = function () {
      objects.RemoveFromGrid(this);
      objects.EndUpdate(this);
      objects.EndDraw(this);
    };

    FloorGuardObject.prototype.DumpInitData = function () {
      var v2 = '' + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y + OBJPARAM_SEPERATION_CHAR + this.dir;
      return v2;
    };

    FloorGuardObject.prototype.IdleAfterDeath = function () {
      this.StopChasing();
      objects.EndUpdate(this);
    };

    FloorGuardObject.prototype.Draw = function () {
      this.mc._x = this.pos.x;
      this.mc._y = this.pos.y;
    };

    FloorGuardObject.prototype.TestVsPlayer = function (guy) {
      var v4 = guy.pos;
      var v3 = this.pos.x - v4.x;
      var v2 = this.pos.y - v4.y;
      var v5 = Math.sqrt(v3 * v3 + v2 * v2);
      if (v5 < this.r + guy.r) {
        v3 /= v5;
        v2 /= v5;
        particles.SpawnZap(this.pos.x - v3 * this.r, this.pos.y - v2 * this.r, NormToRot(-v3, -v2));
        game.KillPlayer(KILLTYPE_ELECTRIC, -v3 * 10, -v2 * 10, v4.x + guy.r * v3, v4.y + guy.r * v2, this);
      }
    };

    FloorGuardObject.prototype.TestVsRagParticle = function (guy) {
      var v5 = guy.pos;
      var v3 = this.pos.x - v5.x;
      var v2 = this.pos.y - v5.y;
      var v4 = Math.sqrt(v3 * v3 + v2 * v2);
      if (v4 < this.r + guy.xw) {
        v3 /= v4;
        v2 /= v4;
        particles.SpawnZap(this.pos.x - v3 * this.r, this.pos.y - v2 * this.r, NormToRot(-v3, -v2));
        player.RagDie(KILLTYPE_ELECTRIC);
        guy.ReportCollisionVsObject(-v3 * 12, -v2 * 12, -v3, -v2, 1);
      }
    };

    FloorGuardObject.prototype.StartChasing = function () {
      this.Update = this.Update_Chase;
      objects.StartDraw(this);
      this.mc.gotoAndStop('floorguard_active');
      if (player.cell.i < this.cell.i) {
        this.dir = -1;
      } else {
        if (this.cell.i < player.cell.i) {
          this.dir = 1;
        } else {
          this.StopChasing();
        }
      }
    };

    FloorGuardObject.prototype.StopChasing = function () {
      this.mc.gotoAndStop('floorguard_idle');
      this.Update = this.Update_Idle;
      objects.EndDraw(this);
    };

    FloorGuardObject.prototype.Update_Idle = function () {
      if (Math.abs(this.cell.j - player.cell.j) == 0) {
        var v2 = player.cell.i;
        if (this.maxi < v2 || v2 < this.mini) {
        } else {
          this.StartChasing();
        }
      }
    };

    FloorGuardObject.prototype.Update_Chase = function () {
      if (this.dir < 0) {
        if (Math.abs(this.pos.x - this.minX) < this.speed) {
          this.pos.x = this.minX;
          this.StopChasing();
        } else {
          this.pos.x += this.dir * this.speed;
        }
      } else {
        if (Math.abs(this.maxX - this.pos.x) < this.speed) {
          this.pos.x = this.maxX;
          this.StopChasing();
        } else {
          this.pos.x += this.dir * this.speed;
        }
      }
      objects.Moved(this);
    };

  }

  frame 1 {
    function DroneObject() {
      this.name = 'drone';
      this.pos = new Vector2(41, 14);
      this.r = tiles.xw * 0.75;
      this.dirList = new Object();
      this.dirList[AI_DIR_R] = new Vector2(1, 0);
      this.dirList[AI_DIR_D] = new Vector2(0, 1);
      this.dirList[AI_DIR_L] = new Vector2(-1, 0);
      this.dirList[AI_DIR_U] = new Vector2(0, -1);
      this.curDir = AI_DIR_R;
      this.curDirV = this.dirList[this.curDir];
      this.goal = new Vector2(54, 85);
      this.speed = tiles.xw * 0.07142857142857143;
      this.curRot = 0;
      this.isChaser = false;
      this.ischasing = false;
      this.waschasing = false;
      this.ai_counter = 0;
      this.ai_counter2 = 0;
      this.view = new Vector2(9, 4);
      this.fireDelayTimer = 0;
      this.targ = new Vector2(4, 5);
      this.targ2 = new Vector2(5, 7);
      this.targ3 = new Vector2(3, 6);
      this.prefireDelay = 0;
      this.postfireDelay = 0;
      this.isFiring = false;
      this.laserPrefireDelay = 30;
      this.laserPostfireDelay = 40;
      this.laserRate = 80;
      this.laserTimer = 0;
      this.laserLen = 7;
      this.chaingunPrefireDelay = 35;
      this.chaingunPostfireDelay = 60;
      this.chaingunMaxNum = 8;
      this.chaingunCurNum = 0;
      this.chaingunRate = 6;
      this.chaingunTimer = 0;
      this.chaingunSpread = 0.3;
      objects.Register(this);
      this.mc = gfx.CreateSprite('debugDroneMC', LAYER_OBJECTS);
      this.mc._visible = false;
      this.eyeMC = this.mc.attachMovie('debugDroneEyeMC', 'drone' + this.UID, this.UID);
      this.snd = new Sound(this.mc);
    }

    DroneObject.prototype.Destruct = function () {
      gfx.DestroyMC(this.mc);
      gfx.DestroyMC(this.beamMC);
      gfx.DestroyMC(this.blastMC);
      gfx.DestroyMC(this.gunMC);
      gfx.DestroyMC(this.eyeMC);
      delete this.mc;
      delete this.beamMC;
      delete this.blastMC;
      delete this.eyeMC;
      delete this.snd;
    };

    DroneObject.prototype.Init = function (params) {
      if (params.length != 6) {
      } else {
        this.pos.x = params[0];
        this.pos.y = params[1];
        this.curDir = params[5];
        this.SetDir(this.curDir);
        objects.AddToGrid(this);
        objects.StartUpdate(this);
        objects.Moved(this);
        this.goal.x = this.cell.pos.x;
        this.pos.x = this.goal.x;
        this.goal.y = this.cell.pos.y;
        this.pos.y = this.goal.y;
        this.SetupDroneType(params[2], Boolean(params[3]), params[4]);
        this.mc._yscale = 2 * this.r;
        this.mc._xscale = this.mc._yscale;
      }
    };

    DroneObject.prototype.UnInit = function () {
      objects.RemoveFromGrid(this);
      objects.EndUpdate(this);
      objects.EndThink(this);
      objects.EndDraw(this);
    };

    DroneObject.prototype.DumpInitData = function () {
      var v2 = '' + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y + OBJPARAM_SEPERATION_CHAR + this.DRONEMOVE + OBJPARAM_SEPERATION_CHAR + Number(this.isChaser) + OBJPARAM_SEPERATION_CHAR + this.DRONEWEAP + OBJPARAM_SEPERATION_CHAR + this.curDir;
      return v2;
    };

    DroneObject.prototype.IdleAfterDeath = function () {
      if (this.isChaser) {
        this.Chase = this.Chase_NoSearch;
        this.ischasing = false;
      }
      this.Think = null;
      if (this.isFiring) {
        this.StopFiring();
      }
    };

    DroneObject.prototype.SetupDroneType = function (movetype, isChaser, weaptype) {
      this.mc.clear();
      this.DRONEMOVE = movetype;
      this.DRONEWEAP = weaptype;
      this.isChaser = isChaser;
      if (movetype == DRONEMOVE_SURFACEFOLLOW_CW) {
        this.GetNewGoal = this.GetNewGoal_Simple;
        this.moveList = MoveList_SurfaceCW;
      } else {
        if (movetype == DRONEMOVE_SURFACEFOLLOW_CCW) {
          this.GetNewGoal = this.GetNewGoal_Simple;
          this.moveList = MoveList_SurfaceCCW;
        } else {
          if (movetype == DRONEMOVE_WANDER_CW) {
            this.GetNewGoal = this.GetNewGoal_Simple;
            this.moveList = MoveList_ChuChuCW;
          } else {
            if (movetype == DRONEMOVE_WANDER_CCW) {
              this.GetNewGoal = this.GetNewGoal_Simple;
              this.moveList = MoveList_ChuChuCCW;
            } else {
              if (movetype == DRONEMOVE_WANDER_ALTERNATING) {
                this.GetNewGoal = this.GetNewGoal_ChuChuAlternating;
              } else {
                if (movetype == DRONEMOVE_WANDER_RANDOM) {
                  this.GetNewGoal = this.GetNewGoal_ChuChuRandom;
                } else {}
              }
            }
          }
        }
      }
      if (weaptype == DRONEWEAP_ZAP) {
        if (isChaser) {
          this.Chase = this.Chase_AxisSearch;
          this.isChaser = true;
          this.ischasing = false;
          this.mc.gotoAndStop('zapdrone_chaseidle');
        } else {
          this.Chase = this.Chase_NoSearch;
          this.isChaser = false;
          this.ischasing = false;
          this.mc.gotoAndStop('zapdrone_move');
        }
        this.name = 'zap drone';
        this.weaptype = DRONEWEAP_ZAP;
        this.speed *= 2;
        this.TestVsPlayer = this.TestVsPlayer_Zap;
        this.TestVsRagParticle = this.TestVsRagParticle_Zap;
      } else {
        if (weaptype == DRONEWEAP_LASER) {
          this.Chase = this.Chase_NoSearch;
          this.isChaser = false;
          this.ischasing = false;
          this.name = 'laser drone';
          this.weaptype = DRONEWEAP_LASER;
          this.speed *= 0.5;
          this.Think = this.Think_TargetPlayer;
          this.Fire = this.Fire_Laser;
          this.StartFiring = this.StartFiring_Laser;
          this.StopFiring = this.StopFiring_Laser;
          this.Update_PreFire = this.Update_PreFire_Laser;
          this.Update_PostFire = this.Update_PostFire_Laser;
          this.prefireDelay = this.laserPrefireDelay;
          this.postfireDelay = this.laserPostfireDelay;
          objects.StartThink(this);
          this.mc.gotoAndStop('laserdrone_move');
          this.beamdx = 0;
          this.beamdy = 0;
          this.beamMC = gfx.CreateEmptySprite(LAYER_OBJECTS);
          this.beamMC._visible = false;
          this.blastMC = gfx.CreateSprite('debugLaserBlastMC', LAYER_OBJECTS);
          this.blastMC._visible = false;
        } else {
          if (weaptype == DRONEWEAP_CHAINGUN) {
            this.Chase = this.Chase_NoSearch;
            this.isChaser = false;
            this.ischasing = false;
            this.name = 'chaingun drone';
            this.weaptype = DRONEWEAP_CHAINGUN;
            this.speed *= 0.75;
            this.Think = this.Think_TargetPlayer;
            this.Fire = this.Fire_Chaingun;
            this.StartFiring = this.StartFiring_Chaingun;
            this.StopFiring = this.StopFiring_Chaingun;
            this.Update_PreFire = this.Update_PreFire_Chaingun;
            this.Update_PostFire = this.Update_PostFire_Chaingun;
            this.prefireDelay = this.chaingunPrefireDelay;
            this.postfireDelay = this.chaingunPostfireDelay;
            objects.StartThink(this);
            this.chainturretRot = 0;
            this.mc.gotoAndStop('chaingundrone_move');
            this.eyeMC = this.mc.attachMovie('debugChainTurretMC', 'chainturret' + this.UID, this.UID);
          } else {}
        }
      }
      this.Draw();
      this.mc._visible = true;
      this.Update = this.Update_Move;
      objects.StartDraw(this);
    };

    DroneObject.prototype.Draw = function () {
      this.mc._x = this.pos.x;
      this.mc._y = this.pos.y;
      var v2 = this.curRot - this.eyeMC._rotation;
      this.eyeMC._rotation += 0.3 * v2;
    };

    DroneObject.prototype.Update_Move = function () {
      ++this.ai_counter;
      var v4 = this.goal.x - this.pos.x;
      var v3 = this.goal.y - this.pos.y;
      var v5 = v4 * v4 + v3 * v3;
      if (v5 < this.speed * this.speed) {
        this.pos.x = this.goal.x;
        this.pos.y = this.goal.y;
        if (this.Chase()) {
          this.ischasing = true;
          this.mc.gotoAndPlay('zapdrone_chaseactive');
        } else {
          this.SetDir(this.GetNewGoal());
          this.ischasing = false;
        }
      } else {
        var v2 = this.speed;
        if (this.ischasing) {
          v2 *= 2;
        }
        this.pos.x += this.curDirV.x * v2;
        this.pos.y += this.curDirV.y * v2;
      }
      objects.Moved(this);
    };

  }

  frame 1 {
    function RotateAIDir(curDir, rot) {
      if (rot < 0 || AI_ROT_270 < rot) {
        return curDir;
      }
      return (curDir + rot) % 4;
    }

    DRONEMOVE_SURFACEFOLLOW_CW = 0;
    DRONEMOVE_SURFACEFOLLOW_CCW = 1;
    DRONEMOVE_WANDER_CW = 2;
    DRONEMOVE_WANDER_CCW = 3;
    DRONEMOVE_WANDER_ALTERNATING = 4;
    DRONEMOVE_WANDER_RANDOM = 5;
    AI_DIR_R = 0;
    AI_DIR_D = 1;
    AI_DIR_L = 2;
    AI_DIR_U = 3;
    AI_ROT_0 = 0;
    AI_ROT_90 = 1;
    AI_ROT_180 = 2;
    AI_ROT_270 = 3;
    MoveList_ChuChuCW = new Array();
    MoveList_ChuChuCW.push(AI_ROT_0);
    MoveList_ChuChuCW.push(AI_ROT_90);
    MoveList_ChuChuCW.push(AI_ROT_270);
    MoveList_ChuChuCW.push(AI_ROT_180);
    MoveList_ChuChuCCW = new Array();
    MoveList_ChuChuCCW.push(AI_ROT_0);
    MoveList_ChuChuCCW.push(AI_ROT_270);
    MoveList_ChuChuCCW.push(AI_ROT_90);
    MoveList_ChuChuCCW.push(AI_ROT_180);
    MoveList_SurfaceCW = new Array();
    MoveList_SurfaceCW.push(AI_ROT_90);
    MoveList_SurfaceCW.push(AI_ROT_0);
    MoveList_SurfaceCW.push(AI_ROT_270);
    MoveList_SurfaceCW.push(AI_ROT_180);
    MoveList_SurfaceCCW = new Array();
    MoveList_SurfaceCCW.push(AI_ROT_270);
    MoveList_SurfaceCCW.push(AI_ROT_0);
    MoveList_SurfaceCCW.push(AI_ROT_90);
    MoveList_SurfaceCCW.push(AI_ROT_180);
    DroneObject.prototype.SetDir = function (dir) {
      if (this.dir != this.curDir) {
        this.curDir = dir;
        this.curDirV = this.dirList[this.curDir];
        if (dir < 2) {
          if (dir == 0) {
            this.curRot = 0;
          } else {
            this.curRot = 90;
          }
        } else {
          if (dir == 2) {
            this.curRot = 180;
          } else {
            this.curRot = -90;
          }
        }
      }
    };

    DroneObject.prototype.TestEdge = function (dir) {
      var v2;
      var v3;
      if (dir == AI_DIR_U) {
        v2 = this.cell.eU;
        v3 = this.cell.nU;
      } else {
        if (dir == AI_DIR_L) {
          v2 = this.cell.eL;
          v3 = this.cell.nL;
        } else {
          if (dir == AI_DIR_D) {
            v2 = this.cell.eD;
            v3 = this.cell.nD;
          } else {
            if (dir == AI_DIR_R) {
              v2 = this.cell.eR;
              v3 = this.cell.nR;
            } else {
              return false;
            }
          }
        }
      }
      if (v2 == EID_OFF) {
        this.goal.x = v3.pos.x;
        this.goal.y = v3.pos.y;
        return true;
      } else {
        return false;
      }
    };

    DroneObject.prototype.Chase_NoSearch = function () {
      return false;
    };

    DroneObject.prototype.Chase_SurfaceGrab = function () {
      this.Chase = this.Chase_AxisSearch;
      this.SetDir(this.surfaceFutureDir);
      return false;
    };

    DroneObject.prototype.Chase_AxisSearch = function () {
      var v5 = player.cell.i - this.cell.i;
      var v3 = player.cell.j - this.cell.j;
      var v2;
      var v4;
      if (Math.abs(v5) < 1) {
        v4 = Math.abs(v3);
        if (player.pos.y < this.pos.y) {
          if (this.curDir == AI_DIR_D) {
            return false;
          } else {
            v2 = AI_DIR_U;
          }
        } else {
          if (this.curDir == AI_DIR_U) {
            return false;
          } else {
            v2 = AI_DIR_D;
          }
        }
      } else {
        if (Math.abs(v3) < 1) {
          v4 = Math.abs(v5);
          if (player.pos.x < this.pos.x) {
            if (this.curDir == AI_DIR_R) {
              return false;
            } else {
              v2 = AI_DIR_L;
            }
          } else {
            if (this.curDir == AI_DIR_L) {
              return false;
            } else {
              v2 = AI_DIR_R;
            }
          }
        } else {
          return false;
        }
      }
      if (this.FindTarget(v2, v4)) {
        this.SetDir(v2);
        if (this.DRONEMOVE < DRONEMOVE_WANDER_CW) {
          this.Chase = this.Chase_SurfaceGrab;
          if (this.DRONEMOVE == DRONEMOVE_SURFACEFOLLOW_CW) {
            rot = AI_ROT_270;
          } else {
            if (this.DRONEMOVE == DRONEMOVE_SURFACEFOLLOW_CCW) {
              rot = AI_ROT_90;
            } else {
              return false;
            }
          }
          this.surfaceFutureDir = RotateAIDir(v2, rot);
        }
        return true;
      } else {
        return false;
      }
    };

    DroneObject.prototype.FindTarget = function (dir, t) {
      var v3 = 0;
      var v2 = this.cell;
      if (dir < 2) {
        if (dir == AI_DIR_R) {
          while (v3 < t) {
            ++v3;
            if (v2.eR == EID_OFF) {
              v2 = v2.nR;
            } else {
              return false;
            }
          }
          while (v2.eR == EID_OFF) {
            ++v3;
            v2 = v2.nR;
          }
          this.goal.x = this.cell.pos.x + v3 * (2 * this.cell.xw);
          return true;
        } else {
          if (dir == AI_DIR_D) {
            while (v3 < t) {
              ++v3;
              if (v2.eD == EID_OFF) {
                v2 = v2.nD;
              } else {
                return false;
              }
            }
            while (v2.eD == EID_OFF) {
              ++v3;
              v2 = v2.nD;
            }
            this.goal.y = this.cell.pos.y + v3 * (2 * this.cell.yw);
            return true;
          } else {
            return false;
          }
        }
      } else {
        if (dir == AI_DIR_L) {
          while (v3 < t) {
            ++v3;
            if (v2.eL == EID_OFF) {
              v2 = v2.nL;
            } else {
              return false;
            }
          }
          while (v2.eL == EID_OFF) {
            ++v3;
            v2 = v2.nL;
          }
          this.goal.x = this.cell.pos.x - v3 * (2 * this.cell.xw);
          return true;
        } else {
          if (dir == AI_DIR_U) {
            while (v3 < t) {
              ++v3;
              if (v2.eU == EID_OFF) {
                v2 = v2.nU;
              } else {
                return false;
              }
            }
            while (v2.eU == EID_OFF) {
              ++v3;
              v2 = v2.nU;
            }
            this.goal.y = this.cell.pos.y - v3 * (2 * this.cell.yw);
            return true;
          } else {
            return false;
          }
        }
      }
    };

    DroneObject.prototype.GetNewGoal_Simple = function () {
      var v3 = this.moveList;
      var v4 = this.curDir;
      var v2 = RotateAIDir(v4, v3[0]);
      if (this.TestEdge(v2)) {
        return v2;
      } else {
        v2 = RotateAIDir(v4, v3[1]);
        if (this.TestEdge(v2)) {
          return v2;
        } else {
          v2 = RotateAIDir(v4, v3[2]);
          if (this.TestEdge(v2)) {
            return v2;
          } else {
            v2 = RotateAIDir(v4, v3[3]);
            if (this.TestEdge(v2)) {
              return v2;
            } else {}
          }
        }
      }
    };

    DroneObject.prototype.GetNewGoal_ChuChuAlternating = function () {
      if (this.ai_counter2 == 0) {
        this.moveList = MoveList_ChuChuCW;
        var v2 = this.GetNewGoal_Simple();
        if (v2 == this.curDir) {
        } else {
          this.ai_counter2 = 1;
        }
        return v2;
      } else {
        this.moveList = MoveList_ChuChuCCW;
        var v2 = this.GetNewGoal_Simple();
        if (v2 == this.curDir) {
          return v2;
        }
        this.ai_counter2 = 0;
        return v2;
      }
    };

    DroneObject.prototype.GetNewGoal_ChuChuRandom = function () {
      if (this.ai_counter % 2 == 0) {
        this.moveList = MoveList_ChuChuCW;
        var v2 = this.GetNewGoal_Simple();
        if (v2 == this.curDir) {
        } else {
          this.ai_counter = 1;
        }
        return v2;
      } else {
        this.moveList = MoveList_ChuChuCCW;
        var v2 = this.GetNewGoal_Simple();
        if (v2 == this.curDir) {
          return v2;
        }
        this.ai_counter = 0;
        return v2;
      }
    };

  }

  frame 1 {
    DRONEWEAP_ZAP = 0;
    DRONEWEAP_LASER = 1;
    DRONEWEAP_CHAINGUN = 2;
    DroneObject.prototype.TestVsPlayer = function (guy) {};

    DroneObject.prototype.TestVsPlayer_Zap = function (guy) {
      var v4 = guy.pos;
      var v3 = this.pos.x - v4.x;
      var v2 = this.pos.y - v4.y;
      var v5 = Math.sqrt(v3 * v3 + v2 * v2);
      if (v5 < this.r + guy.r) {
        v3 /= v5;
        v2 /= v5;
        particles.SpawnZap(this.pos.x - v3 * this.r, this.pos.y - v2 * this.r, NormToRot(-v3, -v2));
        game.KillPlayer(KILLTYPE_ELECTRIC, -v3 * 10, -v2 * 10, v4.x + guy.r * v3, v4.y + guy.r * v2, this);
      }
    };

    DroneObject.prototype.TestVsRagParticle_Zap = function (guy) {
      var v5 = guy.pos;
      var v3 = this.pos.x - v5.x;
      var v2 = this.pos.y - v5.y;
      var v4 = Math.sqrt(v3 * v3 + v2 * v2);
      if (v4 < this.r + guy.xw) {
        v3 /= v4;
        v2 /= v4;
        particles.SpawnZap(this.pos.x - v3 * this.r, this.pos.y - v2 * this.r, NormToRot(-v3, -v2));
        player.RagDie(KILLTYPE_ELECTRIC);
        guy.ReportCollisionVsObject(-v3 * 10, -v2 * 10, -v3, -v2, 1);
      }
    };

    DroneObject.prototype.Think = function () {};

    DroneObject.prototype.Think_TargetPlayer = function () {
      if (QueryRayObj(this.view, this.pos, player.pos, player)) {
        this.StartFiring();
      }
    };

    DroneObject.prototype.StartMoving = function () {
      objects.StartThink(this);
      this.Update = this.Update_Move;
      objects.StartDraw(this);
    };

    DroneObject.prototype.StartFiring_Laser = function () {
      this.mc.gotoAndPlay('laserdrone_prefire');
      objects.EndThink(this);
      objects.EndDraw(this);
      this.fireDelayTimer = 0;
      this.Update = this.Update_PreFire_Laser;
      if (CollideRayvsTiles(this.targ, this.pos, this.view)) {
      } else {}
      this.targ2.x = this.targ.x - this.pos.x;
      this.targ2.y = this.targ.y - this.pos.y;
      this.laserLen = Math.sqrt(this.targ2.x * this.targ2.x + this.targ2.y * this.targ2.y);
      if (this.laserLen == 0) {
        this.StopFiring();
        return undefined;
      }
      this.beamMC._visible = true;
      this.beamMC.clear();
      this.beamMC.lineStyle(0, 13334137, 100);
      this.beamMC.moveTo(this.pos.x, this.pos.y);
      this.beamMC.lineTo(this.targ.x, this.targ.y);
      this.beamdx = this.targ2.x / this.laserLen;
      this.beamdy = this.targ2.y / this.laserLen;
    };

    DroneObject.prototype.StopFiring_Laser = function () {
      this.snd.stop();
      this.mc.gotoAndPlay('laserdrone_postfire');
      this.beamMC._visible = false;
      this.blastMC._visible = false;
      this.blastMC.gotoAndStop(1);
      this.isFiring = false;
      this.fireDelayTimer = 0;
      this.Update = this.Update_PostFire_Laser;
    };

    DroneObject.prototype.Update_PreFire_Laser = function () {
      particles.SpawnLaserCharge(this.pos);
      ++this.fireDelayTimer;
      if (this.prefireDelay <= this.fireDelayTimer) {
        this.isFiring = true;
        this.Fire_Laser();
      }
    };

    DroneObject.prototype.Update_PostFire_Laser = function () {
      ++this.fireDelayTimer;
      if (this.postfireDelay <= this.fireDelayTimer) {
        this.StartMoving();
      }
    };

    DroneObject.prototype.Fire_Laser = function () {
      this.mc.gotoAndStop('laserdrone_firing');
      this.beamMC.clear();
      this.beamMC.lineStyle(3, 8921634, 100);
      this.beamMC.moveTo(this.pos.x, this.pos.y);
      this.beamMC.lineTo(this.targ.x, this.targ.y);
      this.blastMC._x = this.targ.x;
      this.blastMC._y = this.targ.y;
      this.blastMC._visible = true;
      this.blastMC._yscale = 0;
      this.blastMC._xscale = 0;
      this.blastMC.gotoAndPlay(1);
      this.laserLen *= this.laserLen;
      this.laserTimer = 0;
      this.Update = this.Update_FiringLaser;
    };

    DroneObject.prototype.Update_FiringLaser = function () {
      particles.SpawnLaserCharge(this.pos);
      var v10 = this.laserTimer / this.laserRate;
      this.blastMC._yscale = 30 + 200 * v10;
      this.blastMC._xscale = this.blastMC._yscale;
      var v9 = player.pos.x - this.pos.x;
      var v8 = player.pos.y - this.pos.y;
      var v2 = v9 * this.targ2.x + v8 * this.targ2.y;
      v2 /= this.laserLen;
      var v4;
      var v3;
      if (v2 < 0) {
        v4 = this.pos.x;
        v3 = this.pos.y;
      } else {
        if (v2 < 1) {
          v4 = this.pos.x + v2 * this.targ2.x;
          v3 = this.pos.y + v2 * this.targ2.y;
        } else {
          v4 = this.targ.x;
          v3 = this.targ.y;
        }
      }
      var v6 = v4 - player.pos.x;
      var v5 = v3 - player.pos.y;
      if (Math.sqrt(v6 * v6 + v5 * v5) < player.r) {
        this.StopFiring_Laser();
        var v7 = Math.sqrt(this.targ2.x * this.targ2.x + this.targ2.y * this.targ2.y);
        game.KillPlayer(KILLTYPE_LASER, 6 * (this.targ2.x / v7), 6 * (this.targ2.y / v7), v4, v3, this);
        return undefined;
      }
      ++this.laserTimer;
      if (this.laserRate <= this.laserTimer) {
        this.StopFiring();
        return undefined;
      }
    };

    DroneObject.prototype.StartFiring_Chaingun = function () {
      this.mc.gotoAndPlay('chaingundrone_prefire');
      objects.EndThink(this);
      objects.EndDraw(this);
      this.fireDelayTimer = 0;
      this.Update = this.Update_PreFire;
    };

    DroneObject.prototype.StopFiring_Chaingun = function () {
      this.snd.stop();
      this.mc.gotoAndPlay('chaingundrone_postfire');
      this.isFiring = false;
      this.fireDelayTimer = 0;
      this.Update = this.Update_PostFire_Chaingun;
    };

    DroneObject.prototype.Update_PreFire_Chaingun = function () {
      var v4 = player.pos.x - this.pos.x;
      var v3 = player.pos.y - this.pos.y;
      var v2 = NormToRot(v4, v3);
      if (180 < v2) {
        v2 -= 360;
      }
      var v5 = v2 - this.eyeMC._rotation;
      this.eyeMC._rotation += 0.1 * v5;
      ++this.fireDelayTimer;
      if (this.prefireDelay <= this.fireDelayTimer) {
        this.isFiring = true;
        this.Fire_Chaingun();
        this.mc.gotoAndPlay('chaingundrone_fire');
      }
    };

    DroneObject.prototype.Update_PostFire_Chaingun = function () {
      ++this.fireDelayTimer;
      if (this.postfireDelay <= this.fireDelayTimer) {
        this.StartMoving();
      }
    };

    DroneObject.prototype.Fire_Chaingun = function () {
      this.chaingunTimer = 0;
      this.chaingunMaxNum = 4 + game.GetTime() % 5;
      this.chaingunSpread = 0.1 + 0.1 * (1 + game.GetTime() % 3);
      this.chaingunCurNum = 0;
      this.Update = this.Update_FiringChaingun;
      var v3 = player.pos.x - this.pos.x;
      var v2 = player.pos.y - this.pos.y;
      var v4 = Math.sqrt(v3 * v3 + v2 * v2);
      if (v4 == 0) {
        this.StopFiring();
        return undefined;
      }
      v3 /= v4;
      v2 /= v4;
      this.targ.x = v3;
      this.targ.y = v2;
      var v6 = player.pos.x - player.oldpos.x;
      var v5 = player.pos.y - player.oldpos.y;
      var v7 = v6 * -v2 + v5 * v3;
      if (v7 < 0) {
        this.targ2.x = v2;
        this.targ2.y = -v3;
      } else {
        this.targ2.x = -v2;
        this.targ2.y = v3;
      }
    };

    DroneObject.prototype.Update_FiringChaingun = function () {
      ++this.chaingunTimer;
      if (this.chaingunRate <= this.chaingunTimer) {
        this.chaingunTimer = 0;
        if (this.chaingunMaxNum < this.chaingunCurNum) {
          this.StopFiring_Chaingun();
          return undefined;
        }
        var v5 = this.chaingunCurNum / this.chaingunMaxNum - 0.5;
        v5 *= this.chaingunSpread;
        var v7 = this.targ.x + v5 * this.targ2.x;
        var v6 = this.targ.y + v5 * this.targ2.y;
        this.targ3.x = this.pos.x + v7;
        this.targ3.y = this.pos.y + v6;
        if (QueryRayObj(this.view, this.pos, this.targ3, player)) {
          this.StopFiring_Chaingun();
          game.KillPlayer(KILLTYPE_SOFTBULLET, v7 * 5, v6 * 5, this.view.x, this.view.y, this);
        }
        var v3 = this.view.x - this.pos.x;
        var v2 = this.view.y - this.pos.y;
        var v4 = Math.sqrt(v3 * v3 + v2 * v2);
        v3 /= v4;
        v2 /= v4;
        var v8 = NormToRot(v3, v2);
        particles.SpawnChainBullet(this.pos, this.view, v4, v8);
        this.eyeMC._rotation = v8;
        ++this.chaingunCurNum;
      }
    };

  }

  frame 1 {
    function PlayerObject() {
      this.inputList = new Object();
      this.inputList[PINPUT_L] = false;
      this.inputList[PINPUT_R] = false;
      this.inputList[PINPUT_J] = false;
      this.inputList[PINPUT_JTRIG] = false;
      this.pos = new Vector2(45, 70);
      this.oldpos = this.pos.clone();
      this.r = tiles.xw * 0.8333333333333334;
      this.xw = this.r;
      this.yw = this.r;
      this.prevframe = 1;
      this.SetupParams();
      objects.Register(this);
      this.Tick = this.TickNormal;
      this.Stand();
      this.Draw = this.Draw_Normal;
      player = this;
      this.mc = gfx.CreateSprite('testNinjaMCm', LAYER_PLAYER);
      this.snd = gfx.CreateSprite('playerSoundMC', LAYER_PLAYER);
      this.sndloop = gfx.CreateSprite('playerSoundLoopMC', LAYER_PLAYER);
      this.sndControl = new Sound(this.sndloop);
      var v3 = _root._url;
      if (v3.substr(0, 4) != 'file') {
        getURL('http://www.harveycartel.org/metanet/', _top);
      }
    }

    PlayerObject.prototype.Destruct = function () {
      this.raggy.Destruct();
      delete this.raggy;
      gfx.DestroyMC(this.mc);
      delete this.mc;
      gfx.DestroyMC(this.snd);
      delete this.snd;
      gfx.DestroyMC(this.sndloop);
      delete this.mc;
    };

    PlayerObject.prototype.SetupParams = function () {
      this.isDead = false;
      this.timeOfDeath = 0;
      this.maxspeedAir = this.r * 0.5;
      this.maxspeedGround = this.r * 0.5;
      this.groundAccel = 0.15;
      this.airAccel = 0.1;
      this.normGrav = 0.15;
      this.jumpGrav = 0.025;
      this.normDrag = 0.99;
      this.winDrag = 0.8;
      this.wallFriction = 0.13;
      this.skidFriction = 0.92;
      this.standFriction = 0.8;
      this.g = this.normGrav;
      this.d = this.normDrag;
      this.facingDir = 1;
      this.jumpAmt = 1;
      this.jump_y_bias = 2;
      this.max_jump_time = 30;
      this.terminal_vel = this.r * 0.9;
      this.jumptimer = 0;
      this.WAS_IN_AIR = true;
      this.oldv = new Vector2(0, 0);
      this.IN_AIR = true;
      this.NEAR_WALL = false;
      this.wallN = new Vector2(0, 0);
      this.floorN = new Vector2(0, 0);
      this.floorN0 = new Vector2(0, 0);
      this.floorN1 = new Vector2(0, 0);
      this.fCount = 0;
    };

    PlayerObject.prototype.Init = function (params) {
      if (params.length != 2) {
      } else {
        this.oldpos.x = params[0];
        this.pos.x = this.oldpos.x;
        this.oldpos.y = params[1];
        this.pos.y = this.oldpos.y;
        this.xw = this.r;
        this.yw = this.r;
        this.SetupParams();
        objects.AddToGrid(this);
        objects.Moved(this);
        objects.StartDraw(this);
        this.Tick = this.TickNormal;
        this.Stand();
        var v2 = userdata.GetNinjaColor();
        if (v2 != 0) {
          var v4 = new Color(this.mc);
          v4.setRGB(v2);
        }
        this.raggy = new Ragdoll(this.pos, this.r, this.r * 2, v2);
        this.mc._yscale = this.r * 2;
        this.mc._xscale = this.mc._yscale;
        this.mc._x = this.pos.x;
        this.mc._y = this.pos.y;
      }
    };

    PlayerObject.prototype.UnInit = function () {
      objects.RemoveFromGrid(this);
      objects.EndDraw(this);
    };

    PlayerObject.prototype.DumpInitData = function () {
      var v2 = '' + this.pos.x + OBJPARAM_SEPERATION_CHAR + this.pos.y;
      return v2;
    };

    PlayerObject.prototype.FaceDirection = function (dir) {
      if (this.facingDir == dir) {
      } else {
        this.facingDir = dir;
        if (0 < dir) {
          this.mc._xscale = Math.abs(this.mc._xscale);
        } else {
          this.mc._xscale = -1 * Math.abs(this.mc._xscale);
        }
      }
    };

    PlayerObject.prototype.TickNormal = function () {
      p = this.pos;
      o = this.oldpos;
      var v6 = o.x;
      var v5 = o.y;
      o.x = p.x;
      var v4 = o.x;
      o.y = p.y;
      var v3 = o.y;
      var v2 = this.d;
      p.x += v2 * (v4 - v6);
      p.y += v2 * (v3 - v5) + this.g;
      objects.Moved(this);
      this.PrepareToCollide();
      this.CollideVsObjects();
      CollideCirclevsTileMap(this);
      this.HandleCollisions();
      objects.Moved(this);
      this.Think();
    };

    PlayerObject.prototype.TickRagdoll = function () {
      this.raggy.Tick();
    };

    PlayerObject.prototype.PrepareToCollide = function () {
      this.oldv.x = this.pos.x - this.oldpos.x;
      this.oldv.y = this.pos.y - this.oldpos.y;
      this.WAS_IN_AIR = this.IN_AIR;
      this.NEAR_WALL = false;
      this.IN_AIR = true;
      this.fCount = 0;
    };

    PlayerObject.prototype.CollideVsObjects = function () {
      var v2;
      var v3 = this.cell;
      v2 = v3.next;
      while (v2 != null) {
        v2.TestVsPlayer(this);
        v2 = v2.next;
      }
      v2 = v3.nD.next;
      while (v2 != null) {
        v2.TestVsPlayer(this);
        v2 = v2.next;
      }
      v2 = v3.nD.nR.next;
      while (v2 != null) {
        v2.TestVsPlayer(this);
        v2 = v2.next;
      }
      v2 = v3.nD.nL.next;
      while (v2 != null) {
        v2.TestVsPlayer(this);
        v2 = v2.next;
      }
      v2 = v3.nL.next;
      while (v2 != null) {
        v2.TestVsPlayer(this);
        v2 = v2.next;
      }
      v2 = v3.nL.nU.next;
      while (v2 != null) {
        v2.TestVsPlayer(this);
        v2 = v2.next;
      }
      v2 = v3.nR.next;
      while (v2 != null) {
        v2.TestVsPlayer(this);
        v2 = v2.next;
      }
      v2 = v3.nR.nU.next;
      while (v2 != null) {
        v2.TestVsPlayer(this);
        v2 = v2.next;
      }
      v2 = v3.nU.next;
      while (v2 != null) {
        v2.TestVsPlayer(this);
        v2 = v2.next;
      }
    };

    PlayerObject.prototype.HandleCollisions = function () {
      if (0 < this.fCount) {
        this.IN_AIR = false;
        if (1 < this.fCount) {
          var v7 = this.floorN0.x * this.floorN1.x + this.floorN0.y * this.floorN1.y;
          if (0.9 < v7) {
            if (this.floorN0.x == this.floorN.x && this.floorN0.y == this.floorN.y) {
            } else {
              if (this.floorN1.x == this.floorN.x && this.floorN1.y == this.floorN.y) {
              } else {
                this.floorN.x = this.floorN1.x;
                this.floorN.y = this.floorN1.y;
              }
            }
          } else {
            var v2 = this.floorN;
            v2.x = 0.5 * (this.floorN0.x + this.floorN1.x);
            v2.y = 0.5 * (this.floorN0.y + this.floorN1.y);
            var v4 = Math.sqrt(v2.x * v2.x + v2.y * v2.y);
            if (v4 == 0) {
              this.floorN.x = this.floorN0.x;
              this.floorN.y = this.floorN0.y;
            } else {
              this.floorN.x = v2.x / v4;
              this.floorN.y = v2.y / v4;
            }
          }
        } else {
          this.floorN.x = this.floorN0.x;
          this.floorN.y = this.floorN0.y;
        }
        if (this.WAS_IN_AIR) {
          var v5 = this.oldv.x * this.floorN.x + this.oldv.y * this.floorN.y;
          v5 -= 2 * Math.abs(this.floorN.y);
          if (0 < this.oldv.y && v5 < -this.terminal_vel) {
            game.KillPlayer(KILLTYPE_FALL, 0, 0, this.pos.x, this.pos.y, this);
          }
        }
      }
      if (this.IN_AIR && !this.NEAR_WALL) {
        var v3 = this.pos;
        var v6 = this.r + 0.1;
        if (QueryPointvsTileMap(v3.x + v6, v3.y)) {
          this.NEAR_WALL = true;
          this.wallN.x = -1;
          this.wallN.y = 0;
        } else {
          if (QueryPointvsTileMap(v3.x - v6, v3.y)) {
            this.NEAR_WALL = true;
            this.wallN.x = 1;
            this.wallN.y = 0;
          }
        }
      } else {}
    };

    PlayerObject.prototype.ReportCollisionVsWorld = function (px, py, nx, ny, t) {
      this.pos.x += px;
      this.pos.y += py;
      if (0.8 * (this.r * this.r) < px * px + py * py) {
        game.KillPlayer(KILLTYPE_EXPLOSIVE, 0, 0, this.pos.x, this.pos.y, this);
        return undefined;
      }
      if (ny == 0) {
        this.NEAR_WALL = true;
        this.wallN.x = nx;
        this.wallN.y = ny;
      } else {
        if (ny < 0) {
          if (this.fCount == 0) {
            this.floorN0.x = nx;
            this.floorN0.y = ny;
            ++this.fCount;
          } else {
            this.fCount = 1;
            if (1) {
              this.floorN1.x = nx;
              this.floorN1.y = ny;
              ++this.fCount;
            } else {}
          }
        }
      }
    };

    PlayerObject.prototype.ReportCollisionVsObject = function (px, py, nx, ny, obj) {
      this.pos.x += px;
      this.pos.y += py;
      if (ny == 0) {
        this.NEAR_WALL = true;
        this.wallN.x = nx;
        this.wallN.y = ny;
      } else {
        if (ny < 0) {
          if (this.fCount == 0) {
            this.floorN0.x = nx;
            this.floorN0.y = ny;
            ++this.fCount;
          } else {
            this.fCount = 1;
            if (1) {
              this.floorN1.x = nx;
              this.floorN1.y = ny;
              ++this.fCount;
            } else {}
          }
        }
      }
    };

    PlayerObject.prototype.IdleAfterDeath = function () {
      this.CollideVsObjects = null;
    };

  }


  // ===== RETAINED ORIGINAL LINES 10869-12441: player state/physics, NinjaGame, level/replay codecs and loaders =====
  frame 1 {
    PSTATE_STANDING = 0;
    PSTATE_RUNNING = 1;
    PSTATE_SKIDDING = 2;
    PSTATE_JUMPING = 3;
    PSTATE_FALLING = 4;
    PSTATE_WALLSLIDING = 5;
    PSTATE_RAGDOLL = 6;
    PSTATE_CELEBRATING = 7;
    PlayerObject.prototype.Think = function () {
      game.GetInputState(this.inputList);
      var v7 = this.inputList;
      var v19 = v7[PINPUT_R];
      var v22 = v7[PINPUT_L];
      var v25 = v7[PINPUT_J];
      var v15 = v7[PINPUT_JTRIG];
      var v2 = this.pos.x - this.oldpos.x;
      var v4 = this.pos.y - this.oldpos.y;
      var v5 = this.curState;
      var v6 = 1;
      var v3 = 0;
      if (v22) {
        v3 -= 1;
      }
      if (v19) {
        v3 += 1;
      }
      if (this.IN_AIR) {
        var v21 = this.mc._rotation;
        this.mc._rotation -= 0.1 * v21;
        var v8 = v2 + v3 * this.airAccel;
        if (Math.abs(v8) < this.maxspeedAir) {
          v2 = v8;
        } else {}
        this.oldpos.x = this.pos.x - v2;
        if (v5 < 3) {
          this.Fall();
          return undefined;
        }
        if (v5 == PSTATE_JUMPING) {
          ++this.jumptimer;
          if (!v25 || this.jumptimer > this.max_jump_time) {
            this.Fall();
            return undefined;
          }
          return undefined;
        } else {
          if (v5 == PSTATE_FALLING) {
          }
        }
        if (this.NEAR_WALL) {
          if (v15) {
            var v9 = 0;
            var v11 = 0;
            if (v5 == PSTATE_WALLSLIDING && v3 * this.wallN.x < 0) {
              v9 = 1;
              v11 = 0.5;
            } else {
              v9 = 1.5;
              v11 = 0.7;
            }
            particles.SpawnJumpDust(this.pos.x - this.wallN.x * this.r, this.pos.y - this.wallN.y * this.r, this.wallN.x * 90);
            this.Jump(this.wallN.x * v9, this.wallN.y - v11);
            return undefined;
          }
          if (v5 == PSTATE_WALLSLIDING) {
            if (0 < v3 * this.wallN.x) {
              this.Fall();
              return undefined;
            } else {
              var v10 = Math.abs(v4);
              var v12 = -(this.wallFriction * v6) * v10;
              this.oldpos.y = this.pos.y - (v4 + v12);
              particles.SpawnWallDust(this.pos, this.r, this.wallN, v10);
              var v18 = Math.min(100, Math.floor(v10 * 70));
              this.sndControl.setVolume(v18);
              return undefined;
            }
          } else {
            if (0 < v4 && v3 * this.wallN.x < 0) {
              this.Wallslide();
              return undefined;
            }
          }
        } else {
          if (v5 == PSTATE_WALLSLIDING) {
            this.Fall();
            return undefined;
          }
        }
      } else {
        var v8 = v2 + v6 * v3 * this.groundAccel;
        if (Math.abs(v8) < this.maxspeedGround) {
          v2 = v8;
        } else {}
        this.oldpos.x = this.pos.x - v2;
        if (2 < v5) {
          particles.SpawnLandDust(this.pos.x - this.r * this.floorN.x, this.pos.y - this.r * this.floorN.y, NormToRot(this.floorN.x, this.floorN.y) + 90, Math.abs(v2) + v4);
          this.snd.gotoAndPlay('land');
          if (0 < v2 * v3) {
            this.Run(v3);
            return undefined;
          } else {
            this.Skid();
            return undefined;
          }
        }
        if (v15) {
          particles.SpawnJumpDust(this.pos.x - this.floorN.x * this.r, this.pos.y - this.floorN.y * this.r, this.mc._rotation);
          if (v3 * this.floorN.x < 0) {
            this.Jump(0, -0.7);
          } else {
            this.Jump(this.floorN.x, this.floorN.y);
          }
          return undefined;
        }
        if (v5 == PSTATE_RUNNING) {
          var v24 = this.floorN.x;
          var v23 = this.floorN.y;
          var v27 = v2 * -v23 + v4 * v24;
          var v17 = Math.abs(v27);
          var v20 = v2 * v17;
          if (v3 * v20 <= 0) {
            this.Skid();
            return undefined;
          }
          if (v3 * v24 < 0) {
            var v12 = -Math.abs(v24);
            if (v24 < 0) {
              var v13 = -v23;
            } else {
              var v13 = v23;
            }
            var v14 = Math.abs(v23);
            v13 *= 0.5 * v14;
            v12 *= 0.5 * v14;
            var v28 = v2 + v13 * this.groundAccel;
            var v26 = v4 + v12 * this.groundAccel;
            if (Math.abs(v8) < this.maxspeedGround) {
              v2 = v28;
              v4 = v26;
            } else {}
            this.oldpos.x = this.pos.x - v2;
            this.oldpos.y = this.pos.y - v4;
          }
          this.AdvanceRunAnim(v2, v4, v24, v23);
        } else {
          if (v5 == PSTATE_SKIDDING) {
            var v24 = this.floorN.x;
            var v23 = this.floorN.y;
            var v27 = Math.abs(v2 * -v23 + v4 * v24);
            var v20 = v2 * v27;
            if (0 < v20 * v3) {
              this.Run(v3);
              return undefined;
            }
            particles.SpawnFloorDust(this.pos, this.r, this.floorN, this.mc._rotation, this.facingDir, v27);
            if (v27 < 0.1) {
              this.Stand();
              return undefined;
            }
            var v16 = this.skidFriction * v6;
            v2 *= v16;
            this.oldpos.x = this.pos.x - v2;
            var v18 = Math.min(100, Math.floor(v27 * 100));
            this.sndControl.setVolume(v18);
            return undefined;
          } else {
            if (v3 != 0) {
              this.Run(v3);
              return undefined;
            } else {
              var v24 = this.floorN.x;
              var v23 = this.floorN.y;
              var v27 = Math.abs(v2 * -v23 + v4 * v24);
              if (0.1 <= v27) {
                this.Skid();
                return undefined;
              }
              var v16 = this.standFriction * v6;
              v2 *= v16;
              v4 *= v16;
              this.oldpos.x = this.pos.x - v2;
              this.oldpos.y = this.pos.y - v4;
              return undefined;
            }
          }
        }
      }
    };

    PlayerObject.prototype.ThinkRagdoll = function () {};

    PlayerObject.prototype.ThinkCelebrate = function () {
      if (this.IN_AIR) {
        if (this.celeb_wasinair) {
        } else {
          this.d = this.normDrag;
          this.Render = this.RenderInAir;
          this.celeb_wasinair = true;
        }
      } else {
        if (this.celeb_wasinair) {
          this.d = this.winDrag;
          this.Render = this.RenderStatic_Ground;
          var v2 = Math.random();
          if (v2 < 0.1111111111111111) {
            this.mc.gotoAndPlay('CELEBRATE_NEW8');
          } else {
            if (v2 < 0.2222222222222222) {
              this.mc.gotoAndPlay('CELEBRATE_NEW7');
            } else {
              if (v2 < 0.3333333333333333) {
                this.mc.gotoAndPlay('CELEBRATE_NEW6');
              } else {
                if (v2 < 0.4444444444444444) {
                  this.mc.gotoAndPlay('CELEBRATE_NEW5');
                } else {
                  if (v2 < 0.5555555555555556) {
                    this.mc.gotoAndPlay('CELEBRATE_NEW4');
                  } else {
                    if (v2 < 0.6666666666666666) {
                      this.mc.gotoAndPlay('CELEBRATE_NEW3');
                    } else {
                      if (v2 < 0.7777777777777778) {
                        this.mc.gotoAndPlay('CELEBRATE_NEW2');
                      } else {
                        if (v2 < 0.8888888888888888) {
                          this.mc.gotoAndPlay('CELEBRATE_NEW9');
                        } else {
                          this.mc.gotoAndPlay('CELEBRATE_NEW1');
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        } else {}
        this.celeb_wasinair = false;
      }
    };

  }

  frame 1 {
    PlayerObject.prototype.Jump = function (x, y) {
      this.ExitState();
      this.ExitState = this.ExitJump;
      this.curState = PSTATE_JUMPING;
      this.g = this.jumpGrav;
      var v3 = this.pos.x - this.oldpos.x;
      var v2 = this.pos.y - this.oldpos.y;
      if (v3 * x < 0) {
        this.oldpos.x = this.pos.x;
      }
      if (v2 * y < 0) {
        this.oldpos.y = this.pos.y;
      }
      this.pos.x += x * this.jumpAmt;
      this.pos.y += y * (this.jumpAmt + this.jump_y_bias);
      this.jumptimer = 0;
      this.mc._rotation = 0;
      this.Render = this.RenderInAir;
      this.snd.gotoAndPlay('jump');
    };

    PlayerObject.prototype.ExitJump = function () {
      this.g = this.normGrav;
    };

    PlayerObject.prototype.Fall = function () {
      this.ExitState();
      this.ExitState = this.ExitFall;
      this.curState = PSTATE_FALLING;
      this.Render = this.RenderInAir;
    };

    PlayerObject.prototype.ExitFall = function () {};

    PlayerObject.prototype.Wallslide = function () {
      this.ExitState();
      this.ExitState = this.ExitWallslide;
      this.curState = PSTATE_WALLSLIDING;
      this.FaceDirection(-this.wallN.x);
      this.mc._rotation = 0;
      this.Render = this.RenderWallSlide;
      this.mc.gotoAndStop('WALLSLIDE');
      this.sndControl.setVolume(0);
      this.sndloop.gotoAndPlay('wallslide_start');
    };

    PlayerObject.prototype.ExitWallslide = function () {
      this.sndloop.gotoAndPlay('wallslide_stop');
      this.sndControl.setVolume(100);
    };

    PlayerObject.prototype.Skid = function () {
      this.ExitState();
      this.ExitState = this.ExitSkid;
      this.curState = PSTATE_SKIDDING;
      this.Render = this.RenderStatic_Ground;
      this.mc.gotoAndStop('SKID');
      this.sndControl.setVolume(100);
      this.sndloop.gotoAndPlay('skid_start');
    };

    PlayerObject.prototype.ExitSkid = function () {
      this.sndloop.gotoAndPlay('skid_stop');
      this.sndControl.setVolume(100);
    };

    PlayerObject.prototype.Run = function (dirX) {
      this.ExitState();
      this.ExitState = this.ExitRun;
      this.curState = PSTATE_RUNNING;
      this.Render = this.RenderRun;
      this.mc.gotoAndStop('RUN');
      this.runanimleftovers = 0;
    };

    PlayerObject.prototype.ExitRun = function () {};

    PlayerObject.prototype.Stand = function () {
      this.ExitState();
      this.ExitState = this.ExitStand;
      this.curState = PSTATE_STANDING;
      this.Render = this.RenderStatic_Ground;
      this.mc.gotoAndPlay('STAND');
    };

    PlayerObject.prototype.ExitStand = function () {};

    PlayerObject.prototype.Launch = function (x, y) {
      this.oldpos.x = this.pos.x;
      this.oldpos.y = this.pos.y;
      this.pos.x += x;
      this.pos.y += y;
      this.Fall();
    };

    PlayerObject.prototype.Die = function (x, y, px, py, KTYPE) {
      var v7 = Math.random() < 0.5;
      if (KTYPE == KILLTYPE_EXPLOSIVE) {
        if (v7 == false) {
          this.snd.gotoAndPlay('explode1');
        } else {
          this.snd.gotoAndPlay('explode2');
        }
      } else {
        if (KTYPE == KILLTYPE_FALL) {
          this.snd.gotoAndPlay('fall');
        } else {
          if (KTYPE == KILLTYPE_LASER) {
            this.snd.gotoAndPlay('laser');
          } else {
            if (KTYPE == KILLTYPE_ELECTRIC) {
              if (v7 == false) {
                this.snd.gotoAndPlay('zap1');
              } else {
                this.snd.gotoAndPlay('zap1');
              }
            } else {
              if (v7 == false) {
                this.snd.gotoAndPlay('shot1');
              } else {
                this.snd.gotoAndPlay('shot2');
              }
            }
          }
        }
      }
      particles.SpawnBloodSpurt(px, py, x, y, 6 + Math.floor(Math.random() * 8));
      this.ExitState();
      this.ExitState = this.ExitDie;
      this.curState = PSTATE_RAGDOLL;
      this.Tick = this.TickRagdoll;
      this.Think = null;
      this.Draw = this.Draw_Ragdoll;
      this.mc._visible = false;
      this.isDead = true;
      this.timeOfDeath = game.GetTime();
      var v12 = this.pos.x - this.oldpos.x;
      var v11 = this.pos.y - this.oldpos.y;
      this.raggy.Activate();
      this.raggy.MimicMC(v12, v11, this.mc, this.facingDir, this.prevframe);
      if (KTYPE == KILLTYPE_FALL) {
      } else {
        if (!this.IN_AIR) {
          var v8 = this.floorN.x * x + this.floorN.y * y;
          if (v8 < 0) {
            var v6 = v8 * this.floorN.x;
            var v5 = v8 * this.floorN.y;
            var v10 = x - v6;
            var v9 = y - v5;
            static_rend.SetStyle(0, 2237064, 100);
            static_rend.DrawLine_S(this.pos.x, this.pos.y, this.pos.x + v6, this.pos.y + v5);
            static_rend.SetStyle(0, 8921634, 100);
            static_rend.DrawLine_S(this.pos.x, this.pos.y, this.pos.x + v10, this.pos.y + v9);
            x -= v6 * 0.85;
            y -= v5 * 0.85;
            x += v10 * 0.4;
            y += v9 * 0.4;
          }
        }
        if (this.NEAR_WALL) {
          v8 = this.wallN.x * x + this.wallN.y * y;
          if (v8 < 0) {
            v6 = v8 * this.wallN.x;
            v5 = v8 * this.wallN.y;
            v10 = x - v6;
            v9 = y - v5;
            static_rend.SetStyle(0, 2237064, 100);
            static_rend.DrawLine_S(this.pos.x, this.pos.y, this.pos.x + v6, this.pos.y + v5);
            static_rend.SetStyle(0, 8921634, 100);
            static_rend.DrawLine_S(this.pos.x, this.pos.y, this.pos.x + v10, this.pos.y + v9);
            x -= v6 * 0.85;
            y -= v5 * 0.85;
            x += v10 * 0.4;
            y += v9 * 0.4;
          }
        }
        this.raggy.Shove_VertBias(x, y, px, py, this.pos.y, this.r);
      }
      this.TickRagdoll();
    };

    PlayerObject.prototype.RagDie = function (KTYPE) {
      var v2 = Math.random() < 0.5;
      if (KTYPE == KILLTYPE_EXPLOSIVE) {
        this.raggy.chunkAccumulator += Math.random() * 0.6;
        if (!this.raggy.exploded && Math.random() < this.raggy.chunkAccumulator) {
          this.raggy.Explode();
          if (v2 == false) {
            this.snd.gotoAndPlay('explode1');
          } else {
            this.snd.gotoAndPlay('explode2');
          }
        } else {
          if (v2 == false) {
            this.snd.gotoAndPlay('shot1');
          } else {
            this.snd.gotoAndPlay('shot2');
          }
        }
      } else {
        if (KTYPE == KILLTYPE_FALL) {
          this.snd.gotoAndPlay('fall');
        } else {
          if (KTYPE == KILLTYPE_LASER) {
            this.snd.gotoAndPlay('laser');
          } else {
            if (KTYPE == KILLTYPE_ELECTRIC) {
              if (v2 == false) {
                this.snd.gotoAndPlay('zap1');
              } else {
                this.snd.gotoAndPlay('zap1');
              }
            } else {
              if (v2 == false) {
                this.snd.gotoAndPlay('shot1');
              } else {
                this.snd.gotoAndPlay('shot2');
              }
            }
          }
        }
      }
    };

    PlayerObject.prototype.ExitDie = function () {
      if (this.raggy.exploded) {
        this.raggy.Unexplode();
      }
      this.raggy.Deactivate();
      this.isDead = false;
      this.timeOfDeath = 0;
      this.Tick = this.TickNormal;
      this.Think = PlayerObject.prototype.Think;
      this.mc._visible = true;
      this.Draw = this.Draw_Normal;
    };

    PlayerObject.prototype.Celebrate = function () {
      this.ExitState();
      this.ExitState = this.ExitCelebrate;
      this.curState = PSTATE_CELEBRATING;
      this.Think = this.ThinkCelebrate;
      this.celeb_wasinair = this.IN_AIR;
    };

    PlayerObject.prototype.ExitCelebrate = function () {
      this.d = this.normDrag;
      this.Think = PlayerObject.prototype.Think;
    };

  }

  frame 1 {
    PlayerObject.prototype.Draw_Normal = function () {
      this.prevframe = this.mc._currentframe;
      this.Render();
    };

    PlayerObject.prototype.Draw_Ragdoll = function () {
      this.raggy.Draw();
    };

    PlayerObject.prototype.FaceMovement = function () {
      var v2 = this.pos.x - this.oldpos.x;
      if (v2 == 0) {
      } else {
        if (0 < v2) {
          this.FaceDirection(1);
        } else {
          if (v2 < 0) {
            this.FaceDirection(-1);
          } else {}
        }
      }
    };

    PlayerObject.prototype.RenderWallSlide = function () {
      this.mc._x = this.pos.x;
      this.mc._y = this.pos.y;
    };

    PlayerObject.prototype.RenderInAir = function () {
      this.FaceMovement();
      this.mc._x = this.pos.x;
      this.mc._y = this.pos.y;
      var v2 = this.pos.y - this.oldpos.y;
      var v5 = -1;
      var v4 = 2.5;
      var v3 = 0;
      if (v2 < 0) {
        if (v2 < v5) {
          v3 = -1;
        } else {
          v3 = -(v2 / v5);
        }
      } else {
        if (v4 < v2) {
          v3 = 1;
        } else {
          v3 = Math.sqrt(v2 / v4);
        }
      }
      var v6 = Math.floor(v3 * 9);
      this.mc.gotoAndStop(94 + v6);
    };

    PlayerObject.prototype.RenderRun = function () {
      this.FaceMovement();
      this.mc.gotoAndStop(this.runanimcurframe);
      this.mc._x = this.pos.x;
      this.mc._y = this.pos.y;
      var v3 = this.floorN.x;
      var v4 = this.floorN.y;
      var v2 = 0;
      if (v3 == 0) {
        v2 = -90;
      } else {
        if (v4 == 0) {
          if (v3 < 0) {
            v2 = 180;
          } else {
            v2 = 0;
          }
        } else {
          v2 = Math.atan(v4 / v3) / 0.0174532925199433;
          if (v3 < 0) {
            v2 += 180;
          }
        }
      }
      v2 += 90;
      this.mc._rotation = v2;
    };

    PlayerObject.prototype.AdvanceRunAnim = function (vx, vy, nx, ny) {
      var v5 = Math.abs(vx * -ny + vy * nx);
      var v3 = 13;
      var v8 = 0.9;
      var v6 = 72;
      var v9 = this.mc._currentframe - v3;
      var v2 = v5 / v8;
      v2 += this.runanimleftovers;
      var v4 = Math.floor(v2);
      this.runanimleftovers = v2 - v4;
      var v7 = (v9 + v4) % v6;
      this.runanimcurframe = v3 + v7;
    };

    PlayerObject.prototype.RenderDebug = function () {
      static_rend.SetStyle(0, 0, 25);
      static_rend.DrawAABB(this.pos, this.xw, this.yw);
      static_rend.DrawCircle(this.pos, this.r);
    };

    PlayerObject.prototype.RenderStatic = function () {
      this.FaceMovement();
      this.mc._x = this.pos.x;
      this.mc._y = this.pos.y;
    };

    PlayerObject.prototype.RenderStatic_Ground = function () {
      this.FaceMovement();
      this.mc._x = this.pos.x;
      this.mc._y = this.pos.y;
      var v3 = this.floorN.x;
      var v4 = this.floorN.y;
      var v2 = 0;
      if (v3 == 0) {
        v2 = -90;
      } else {
        if (v4 == 0) {
          if (v3 < 0) {
            v2 = 180;
          } else {
            v2 = 0;
          }
        } else {
          v2 = Math.atan(v4 / v3) / 0.0174532925199433;
          if (v3 < 0) {
            v2 += 180;
          }
        }
      }
      v2 += 90;
      this.mc._rotation = v2;
    };

  }

  frame 1 {
    function NinjaGame() {
      this.SetDemoFormat(true);
      this.KEYDEF_L = userdata.GetLeftKey();
      this.KEYDEF_R = userdata.GetRightKey();
      this.KEYDEF_J = userdata.GetJumpKey();
      this.playerMaxTime = 3600;
      this.playerCurTime = 3600;
      this.playerStartingTime = 3600;
      this.playerBonusTime = 80;
      this.isTimeTrial = false;
      this.RECORDING_DEMO = false;
      this.mapStr = '';
      this.objStr = '';
      this.tickCounter = 0;
      this.demoTickCount = 0;
      this.GetInputState = this.GetInputState_Normal;
      var v3 = _root._url;
      if (v3.substr(0, 4) != 'file') {
        getURL('http://www.harveycartel.org/metanet/', _top);
      }
    }

    NinjaGame.prototype.SetDemoFormat = function (isCompressed) {
      if (isCompressed) {
        this.InstallCompressedCodec();
      } else {
        this.InstallComplexCodec();
      }
    };

    NinjaGame.prototype.LoadDemo = function (str) {
      if (str.charAt(0) == 'A') {
        this.SetDemoFormat(true);
        this.LoadDemo_Compressed(str);
      } else {
        this.SetDemoFormat(false);
        this.LoadDemo_Complex(str);
      }
    };

    NinjaGame.prototype.DumpDemoData = function (isCompressed) {
      if (isCompressed) {
        this.SetDemoFormat(true);
        return this.DumpDemoData_Compressed();
      } else {
        this.SetDemoFormat(false);
        return this.DumpDemoData_Complex();
      }
    };

    NinjaGame.prototype.SetKeyDefs = function (jdef, ldef, rdef) {
      this.KEYDEF_L = ldef;
      this.KEYDEF_R = rdef;
      this.KEYDEF_J = jdef;
    };

    NinjaGame.prototype.InitNewGame = function (gamemode) {
      if (gamemode == 2) {
        this.isTimeTrial = false;
        this.isCustom = true;
      } else {
        if (gamemode == 1) {
          this.isTimeTrial = true;
          this.isCustom = false;
        } else {
          if (gamemode == 0) {
            this.isTimeTrial = false;
            this.isCustom = false;
          }
        }
      }
      this.playerStartingTime = this.playerMaxTime;
      this.playerCurTime = this.playerStartingTime;
      this.tickCounter = 0;
    };

    NinjaGame.prototype.InitNewLevel = function () {
      if (this.isTimeTrial) {
        this.playerStartingTime = this.playerMaxTime;
      } else {
        if (this.isCustom) {
          this.playerStartingTime = this.playerMaxTime;
        } else {
          this.playerStartingTime = this.playerCurTime;
        }
      }
      this.tickCounter = 0;
    };

    NinjaGame.prototype.InitRetryLevel = function () {
      this.playerCurTime = this.playerStartingTime;
      this.tickCounter = 0;
    };

    NinjaGame.prototype.Tick = function () {
      debug_rend.Clear();
      static_rend.Clear();
      objects.Tick();
      player.Tick();
      ++this.tickCounter;
    };

    NinjaGame.prototype.Draw = function () {
      objects.Draw();
    };

    NinjaGame.prototype.DrawPlayerTime = function () {
      gui.DrawPlayerTime(this.playerCurTime, this.playerMaxTime);
    };

    NinjaGame.prototype.FillPlayerTime = function () {
      gui.FillPlayerTime(this.playerCurTime, this.playerMaxTime);
    };

    NinjaGame.prototype.GetPlayerTime = function () {
      return this.playerCurTime;
    };

    NinjaGame.prototype.GetPlayerLevelTime = function () {
      var v2 = this.playerMaxTime + (this.playerCurTime - this.playerStartingTime);
      return v2;
    };

    NinjaGame.prototype.GetTime = function () {
      return this.tickCounter;
    };

    NinjaGame.prototype.GiveBonusTime = function () {
      this.playerCurTime += this.playerBonusTime;
    };

    KILLTYPE_ELECTRIC = 0;
    KILLTYPE_EXPLOSIVE = 1;
    KILLTYPE_WEAKBULLET = 2;
    KILLTYPE_HARDBULLET = 3;
    KILLTYPE_FALL = 4;
    KILLTYPE_LASER = 5;
    NinjaGame.prototype.KillPlayer = function (killtype, fx, fy, px, py, obj) {
      if (!player.isDead) {
        player.Die(fx, fy, px, py, killtype);
        if (killtype == KILLTYPE_EXPLOSIVE) {
          player.raggy.Explode();
        }
        App_PlayerDeathEvent();
        var v1 = 'You were killed by ';
        var v3 = objects.GetObjType(obj);
        if (v3 == OBJTYPE_PLAYER) {
          v1 += 'yourself!! looooooser!!';
          if (!APP_DEBUG_DEATH) {
            userdata.IncrementKillCount('player');
          }
        } else {
          v1 += 'a ' + obj.name;
          if (!APP_DEBUG_DEATH) {
            userdata.IncrementKillCount(obj.name);
          }
        }
        console.AddLine(v1);
      } else {}
    };

  }

  frame 1 {
    LEVEL_SEPERATION_CHAR = '|';
    OBJECT_SEPERATION_CHAR = '!';
    OBJTYPE_SEPERATION_CHAR = '^';
    OBJPARAM_SEPERATION_CHAR = ',';
    NinjaGame.prototype.DumpLevelData = function () {
      var v2 = this.DumpMapData();
      var v4 = this.DumpObjData();
      var v3 = v2 + LEVEL_SEPERATION_CHAR + v4;
      return v3;
    };

    NinjaGame.prototype.DumpMapData = function () {
      var v1 = tiles.GetTileStates();
      return v1;
    };

    NinjaGame.prototype.DumpObjData = function () {
      var v1 = objects.GetObjectStates();
      return v1;
    };

  }

  frame 1 {
    PINPUT_L = 0;
    PINPUT_R = 1;
    PINPUT_J = 2;
    PINPUT_JTRIG = 3;
    BITSHIFT_L = 0;
    BITSHIFT_R = 1;
    BITSHIFT_J = 2;
    BITSHIFT_JTRIG = 3;
    BITMASK_L = 1 << BITSHIFT_L;
    BITMASK_R = 1 << BITSHIFT_R;
    BITMASK_J = 1 << BITSHIFT_J;
    BITMASK_JTRIG = 1 << BITSHIFT_JTRIG;
    NinjaGame.prototype.GetInputState_Normal = function (inList) {
      inList[PINPUT_L] = Key.isDown(this.KEYDEF_L);
      inList[PINPUT_R] = Key.isDown(this.KEYDEF_R);
      var v3 = inList[PINPUT_J];
      inList[PINPUT_J] = Key.isDown(this.KEYDEF_J);
      inList[PINPUT_JTRIG] = inList[PINPUT_J] && !v3;
      if (this.RECORDING_DEMO) {
        this.RecordFrame(inList);
      }
    };

    NinjaGame.prototype.GetDemoTickCount = function () {
      return this.demoTickCount;
    };

  }

  frame 1 {
    function EncodeOctalString_RLEo6(str) {
      var v8 = '';
      var v5 = str.length;
      var v3 = 0;
      while (v3 < v5) {
        var v4 = str.charAt(v3);
        var v2 = 0;
        var v1 = v3;
        for (;;) {
          if (!(v1 < v5 && v2 < RLEo6_MAX_RUN_LEN)) break;
          if (str.charAt(v1) == v4) {
            ++v2;
          } else {
            break;
          }
          ++v1;
        }
        if (v2 < 5) {
          v8 += v4;
        } else {
          var v7 = EncodeCharRun_RLEo6(v4, v2);
          v8 += v7;
          v3 = v1 - 1;
        }
        ++v3;
      }
      return v8;
    }

    function EncodeCharRun_RLEo6(char, len) {
      var v1 = '7';
      v1 += char;
      if (len < 5) {
        return '';
      }
      len -= 4;
      var v8 = 56;
      var v6 = 7;
      var v9 = (len & v8) >> 3;
      var v10 = len & v6;
      var v7 = new Number(v9);
      var v5 = new Number(v10);
      var v3 = v7.toString(8);
      var v4 = v5.toString(8);
      v1 += v3;
      v1 += v4;
      return v1;
    }

    function DecodeCharRun_RLEo6(runStr) {
      var v3 = runStr.charAt(1);
      var v5 = runStr.charAt(2);
      var v6 = runStr.charAt(3);
      var v7 = parseInt(v5, 8);
      var v8 = parseInt(v6, 8);
      var v2 = 0;
      v2 += v7 << 3;
      v2 += v8;
      v2 += 4;
      var v1 = '';
      while (v1.length < v2) {
        v1 += v3;
      }
      return v1;
    }

    function DecodeOctalString_RLEo6(str) {
      var v5 = '';
      var v7 = str.length;
      var v1 = 0;
      while (v1 < v7) {
        var v2 = str.charAt(v1);
        if (v2 == '7') {
          var v3 = str.substr(v1, 4);
          var v4 = DecodeCharRun_RLEo6(v3);
          v5 += v4;
          v1 += 3;
        } else {
          v5 += v2;
        }
        ++v1;
      }
      return v5;
    }

    RLEo6_MAX_RUN_LEN = 67;
  }

  frame 1 {
    function RLEo6c_SetTokenRange(bottom, top) {
      if (top < bottom) {
        return undefined;
      }
      RLEo6c_RUN_CHARSHIFT = bottom;
      RLEo6c_MAX_RUN_LEN = top - bottom;
    }

    function EncodeOctalString_RLEo6c(str) {
      var v8 = '';
      var v5 = PackOctalString(str);
      var v6 = v5.length;
      var v3 = 0;
      while (v3 < v6) {
        var v4 = v5.charAt(v3);
        var v2 = 0;
        var v1 = v3;
        for (;;) {
          if (!(v1 < v6 && v2 < RLEo6c_MAX_RUN_LEN)) break;
          if (v5.charAt(v1) == v4) {
            ++v2;
          } else {
            break;
          }
          ++v1;
        }
        if (v2 < RLEo6c_MIN_RUN_LEN) {
          v8 += v4;
        } else {
          var v7 = EncodeCharRun_RLEo6c(v4, v2);
          v8 += v7;
          v3 = v1 - 1;
        }
        ++v3;
      }
      return v8;
    }

    function EncodeCharRun_RLEo6c(char, len) {
      var v1 = '';
      len += RLEo6c_RUN_CHARSHIFT;
      var v2 = String.fromCharCode(len);
      v1 += v2;
      v1 += char;
      return v1;
    }

    function DecodeCharRun_RLEo6c(runStr) {
      var v2 = runStr.charCodeAt(0);
      v2 -= RLEo6c_RUN_CHARSHIFT;
      var v3 = runStr.charAt(1);
      var v1 = '';
      while (v1.length < v2) {
        v1 += v3;
      }
      return v1;
    }

    function DecodeOctalString_RLEo6c(str) {
      var v7 = '';
      var v8 = str.length;
      var v1 = 0;
      while (v1 < v8) {
        var v4 = str.charCodeAt(v1);
        if (RLEo6c_RUN_CHARSHIFT <= v4) {
          var v3 = str.substr(v1, 2);
          var v6 = DecodeCharRun_RLEo6c(v3);
          v7 += v6;
          v1 += RLEo6c_MIN_RUN_LEN - 1;
        } else {
          var v5 = str.charAt(v1);
          v7 += v5;
        }
        ++v1;
      }
      var v9 = UnpackOctalString(v7);
      return v9;
    }

    RLEo6c_RUN_CHARSHIFT = 100;
    RLEo6c_MIN_RUN_LEN = 3;
    RLEo6c_MAX_RUN_LEN = 50;
  }

  frame 1 {
    function PackOctalString(str) {
      var v10 = str.length;
      if (v10 % 2 == 1) {
        str += '3';
      }
      var v9 = '';
      v10 = str.length;
      var v2 = 0;
      while (v2 < v10) {
        var v3 = str.charAt(v2);
        var v4 = str.charAt(v2 + 1);
        var v7 = parseInt(v3, 8);
        var v6 = parseInt(v4, 8);
        var v1 = 0;
        v1 += v7 << 3;
        v1 += v6;
        v1 += 34;
        if (91 < v1) {
          v1 += 1;
        }
        var v5 = String.fromCharCode(v1);
        v9 += v5;
        v2 += 2;
      }
      return v9;
    }

    function UnpackOctalString(str) {
      var v3 = '';
      var v12 = str.length;
      var v2 = 0;
      while (v2 < v12) {
        var v1 = str.charCodeAt(v2);
        if (91 < v1) {
          v1 -= 1;
        }
        v1 -= 34;
        var v9 = 56;
        var v7 = 7;
        var v10 = (v1 & v9) >> 3;
        var v11 = v1 & v7;
        var v8 = new Number(v10);
        var v6 = new Number(v11);
        var v4 = v8.toString(8);
        var v5 = v6.toString(8);
        v3 += v4;
        v3 += v5;
        ++v2;
      }
      if (v3.charAt(v3.length - 1) == '3') {
        v3 = v3.substr(0, v3.length - 1);
      }
      return v3;
    }

  }

  frame 1 {
    function BeginIncrementalCompression(str, callback) {
      _root.APP_INC_ENCODE_SOURCE = str;
      _root.APP_INC_ENCODE_OUTPUT = '';
      _root.APP_INC_ENCODE_CALLBACK = callback;
      _root.APP_INC_ENCODE_STEP = 0;
      _root.APP_INC_ENCODE_ITERATOR = 0;
      _root.APP_INC_ENCODE_STRLEN = APP_INC_ENCODE_SOURCE.length;
      _root.APP_INC_ENCODE_INTERVAL = setInterval(_root.CompressDemo_Inc, 15);
    }

    function CompressDemo_Inc(str) {
      if (APP_INC_ENCODE_STEP == 0) {
        if (!EncodeOctalString_RLEo6_Inc()) {
          APP_INC_ENCODE_STEP = 1;
          APP_INC_ENCODE_ITERATOR = 0;
          APP_INC_ENCODE_SOURCE = PackOctalString(APP_INC_ENCODE_OUTPUT);
          APP_INC_ENCODE_OUTPUT = '';
          APP_INC_ENCODE_STRLEN = APP_INC_ENCODE_SOURCE.length;
        }
      } else {
        if (APP_INC_ENCODE_STEP == 1) {
          if (!EncodeOctalString_RLEo6c_Inc()) {
            var v1 = 'A' + APP_INC_ENCODE_OUTPUT;
            APP_INC_ENCODE_CALLBACK(v1);
            clearInterval(APP_INC_ENCODE_INTERVAL);
          }
        }
      }
    }

    function EncodeOctalString_RLEo6_Inc() {
      var v6 = 0;
      var v7 = 40;
      var v4 = APP_INC_ENCODE_SOURCE;
      while (v6 < v7) {
        var v3 = v4.charAt(APP_INC_ENCODE_ITERATOR);
        var v2 = 0;
        var v1 = APP_INC_ENCODE_ITERATOR;
        for (;;) {
          if (!(v1 < APP_INC_ENCODE_STRLEN && v2 < RLEo6_MAX_RUN_LEN)) break;
          if (v4.charAt(v1) == v3) {
            ++v2;
          } else {
            break;
          }
          ++v1;
        }
        if (v2 < 5) {
          APP_INC_ENCODE_OUTPUT += v3;
        } else {
          var v5 = EncodeCharRun_RLEo6(v3, v2);
          APP_INC_ENCODE_OUTPUT += v5;
          APP_INC_ENCODE_ITERATOR = v1 - 1;
        }
        ++v6;
        ++APP_INC_ENCODE_ITERATOR;
        if (APP_INC_ENCODE_STRLEN <= APP_INC_ENCODE_ITERATOR) {
          return false;
        }
      }
      if (APP_INC_ENCODE_ITERATOR < APP_INC_ENCODE_STRLEN) {
        return true;
      } else {
        return false;
      }
    }

    function EncodeOctalString_RLEo6c_Inc() {
      var v6 = 0;
      var v7 = 40;
      var v4 = APP_INC_ENCODE_SOURCE;
      while (v6 < v7) {
        var v3 = v4.charAt(APP_INC_ENCODE_ITERATOR);
        var v2 = 0;
        var v1 = APP_INC_ENCODE_ITERATOR;
        for (;;) {
          if (!(v1 < APP_INC_ENCODE_STRLEN && v2 < RLEo6_MAX_RUN_LEN)) break;
          if (v4.charAt(v1) == v3) {
            ++v2;
          } else {
            break;
          }
          ++v1;
        }
        if (v2 < RLEo6c_MIN_RUN_LEN) {
          APP_INC_ENCODE_OUTPUT += v3;
        } else {
          var v5 = EncodeCharRun_RLEo6c(v3, v2);
          APP_INC_ENCODE_OUTPUT += v5;
          APP_INC_ENCODE_ITERATOR = v1 - 1;
        }
        ++v6;
        ++APP_INC_ENCODE_ITERATOR;
        if (APP_INC_ENCODE_STRLEN <= APP_INC_ENCODE_ITERATOR) {
          return false;
        }
      }
      if (APP_INC_ENCODE_ITERATOR < APP_INC_ENCODE_STRLEN) {
        return true;
      } else {
        return false;
      }
    }

    APP_INC_ENCODE_INTERVAL = null;
    APP_INC_ENCODE_SOURCE = '';
    APP_INC_ENCODE_OUTPUT = '';
    APP_INC_ENCODE_CALLBACK = null;
    APP_INC_ENCODE_STEP = 0;
    APP_INC_ENCODE_STRLEN = 0;
    APP_INC_ENCODE_ITERATOR = 0;
    NinjaGame.prototype.DumpDemoData_Inc = function () {
      var v6 = '';
      var v3 = 0;
      while (v3 < this.demoList.length) {
        var v5 = this.demoList[v3] & BITMASK_BOTTOM30;
        var v4 = new Number(v5);
        var v2 = v4.toString(8);
        while (v2.length < 10) {
          v2 = '0' + v2;
        }
        v6 += v2;
        ++v3;
      }
      return v6;
    };

  }

  frame 1 {
    function CompressDemo(str) {
      var v2 = EncodeOctalString_RLEo6(str);
      var v1 = EncodeOctalString_RLEo6c(v2);
      v1 = 'A' + v1;
      return v1;
    }

    function DecompressDemo(str) {
      var v2 = DecodeOctalString_RLEo6c(str.substr(1));
      var v1 = DecodeOctalString_RLEo6(v2);
      return v1;
    }

    NinjaGame.prototype.InstallCompressedCodec = function () {
      this.StartRecordingDemo = this.StartRecordingDemo_Compressed;
      this.StopRecordingDemo = this.StopRecordingDemo_Compressed;
      this.StartDemoPlayback = this.StartDemoPlayback_Compressed;
      this.StopDemoPlayback = this.StopDemoPlayback_Compressed;
      this.RecordFrame = this.RecordFrame_Compressed;
      this.GetInputState_DemoPlayback = this.GetInputState_DemoPlayback_Compressed;
    };

    NinjaGame.prototype.InstallComplexCodec = function () {
      this.StartRecordingDemo = this.StartRecordingDemo_Complex;
      this.StopRecordingDemo = this.StopRecordingDemo_Complex;
      this.StartDemoPlayback = this.StartDemoPlayback_Complex;
      this.StopDemoPlayback = this.StopDemoPlayback_Complex;
      this.RecordFrame = this.RecordFrame_Complex;
      this.GetInputState_DemoPlayback = this.GetInputState_DemoPlayback_Complex;
    };

  }

  frame 1 {
    BITMASK_BOTTOM30 = 0;
    var i = 0;
    while (i < 30) {
      BITMASK_BOTTOM30 += 1 << i;
      ++i;
    }
    BITMASK_FRAME_COMPRESSED = BITMASK_L + BITMASK_R + BITMASK_J;
    shiftList_Compressed = new Array();
    shiftList_Compressed[0] = 27;
    shiftList_Compressed[1] = 24;
    shiftList_Compressed[2] = 21;
    shiftList_Compressed[3] = 18;
    shiftList_Compressed[4] = 15;
    shiftList_Compressed[5] = 12;
    shiftList_Compressed[6] = 9;
    shiftList_Compressed[7] = 6;
    shiftList_Compressed[8] = 3;
    shiftList_Compressed[9] = 0;
    NUM_BITPACKS_COMPRESSED = shiftList_Compressed.length;
    NinjaGame.prototype.StartRecordingDemo_Compressed = function () {
      console.AddLine('-demo recording started..');
      this.GetInputState = this.GetInputState_Normal;
      this.RECORDING_DEMO = true;
      this.demoTickCount = 0;
      this.demoList = new Array();
      this.demoList.push(0);
      this.demoCurShift = 0;
    };

    NinjaGame.prototype.StopRecordingDemo_Compressed = function () {
      this.RECORDING_DEMO = false;
      this.demoTickCount -= 1;
      if (this.demoTickCount < 0) {
        this.demoTickCount = 0;
      }
      console.AddLine('-demo recording stopped.');
    };

    NinjaGame.prototype.StartDemoPlayback_Compressed = function () {
      console.AddLine('-demo playback started..');
      this.GetInputState = this.GetInputState_DemoPlayback;
      this.jtrig_playback_cache = false;
      this.demoCurPlayEntry = 0;
      this.demoCurShift = 0;
    };

    NinjaGame.prototype.StopDemoPlayback_Compressed = function () {
      console.AddLine('-demo playback stopped.');
      this.GetInputState = this.GetInputState_Normal;
    };

    NinjaGame.prototype.RecordFrame_Compressed = function (inList) {
      if (5000 <= this.demoList.length) {
        this.StopRecordingDemo();
        return undefined;
      }
      if (inList[PINPUT_L] && inList[PINPUT_R]) {
        inList[PINPUT_R] = false;
        inList[PINPUT_L] = false;
      }
      var v4 = Number(inList[PINPUT_L]);
      var v3 = Number(inList[PINPUT_R]);
      var v5 = Number(inList[PINPUT_J]);
      var v6 = +(v4 << BITSHIFT_L) + (v3 << BITSHIFT_R) + (v5 << BITSHIFT_J);
      var v7 = shiftList_Compressed[this.demoCurShift];
      this.demoList[this.demoList.length - 1] += v6 << v7;
      ++this.demoCurShift;
      if (NUM_BITPACKS_COMPRESSED <= this.demoCurShift) {
        this.demoList.push(0);
        this.demoCurShift = 0;
      }
      ++this.demoTickCount;
    };

    NinjaGame.prototype.GetInputState_DemoPlayback_Compressed = function (inList) {
      if (this.demoTickCount <= game.GetTime()) {
        this.StopDemoPlayback();
        return undefined;
      }
      var v2 = this.demoList[this.demoCurPlayEntry];
      v2 >>= shiftList_Compressed[this.demoCurShift];
      v2 &= BITMASK_FRAME_COMPRESSED;
      var v5 = v2 & BITMASK_L;
      var v4 = v2 & BITMASK_R;
      var v6 = v2 & BITMASK_J;
      inList[PINPUT_L] = Boolean(v5);
      inList[PINPUT_R] = Boolean(v4);
      inList[PINPUT_J] = Boolean(v6);
      inList[PINPUT_JTRIG] = inList[PINPUT_J] && !this.jtrig_playback_cache;
      this.jtrig_playback_cache = inList[PINPUT_J];
      ++this.demoCurShift;
      if (NUM_BITPACKS_COMPRESSED <= this.demoCurShift) {
        ++this.demoCurPlayEntry;
        this.demoCurShift = 0;
      }
    };

    NinjaGame.prototype.LoadDemo_Compressed = function (demoStr) {
      var v5 = DecompressDemo(demoStr);
      this.demoList = new Array();
      var v2 = 0;
      while (v2 < v5.length) {
        var v4 = parseInt(v5.substr(v2, 10), 8);
        var v3 = new Number(v4);
        this.demoList.push(v3.valueOf());
        v2 += 10;
      }
      console.AddLine('-demo loaded.');
    };

    NinjaGame.prototype.DumpDemoData_Compressed = function () {
      var v6 = '';
      var v3 = 0;
      while (v3 < this.demoList.length) {
        var v5 = this.demoList[v3] & BITMASK_BOTTOM30;
        var v4 = new Number(v5);
        var v2 = v4.toString(8);
        while (v2.length < 10) {
          v2 = '0' + v2;
        }
        v6 += v2;
        ++v3;
      }
      var v7 = CompressDemo(v6);
      return v7;
    };

  }

  frame 1 {
    DEMOFRAME_SEPERATION_CHAR = '|';
    DEMOTICKS_SEPERATION_CHAR = ':';
    BITMASK_FRAME_COMPLEX = BITMASK_L + BITMASK_R + BITMASK_J + BITMASK_JTRIG;
    shiftList_Complex = new Array();
    shiftList_Complex[0] = 0;
    shiftList_Complex[1] = 4;
    shiftList_Complex[2] = 8;
    shiftList_Complex[3] = 12;
    shiftList_Complex[4] = 16;
    shiftList_Complex[5] = 20;
    shiftList_Complex[6] = 24;
    NUM_BITPACKS_COMPLEX = shiftList_Complex.length;
    NinjaGame.prototype.StartRecordingDemo_Complex = function () {
      console.AddLine('-demo recording started..');
      this.GetInputState = this.GetInputState_Normal;
      this.RECORDING_DEMO = true;
      this.demoTickCount = 0;
      this.demoList = new Array();
      this.demoList.push(0);
      this.demoCurShift = 0;
    };

    NinjaGame.prototype.StopRecordingDemo_Complex = function () {
      this.RECORDING_DEMO = false;
      this.demoTickCount -= 1;
      if (this.demoTickCount < 0) {
        this.demoTickCount = 0;
      }
      console.AddLine('-demo recording stopped.');
    };

    NinjaGame.prototype.LoadDemo_Complex = function (demoStr) {
      var v4 = demoStr.split(DEMOTICKS_SEPERATION_CHAR);
      this.demoTickCount = Number(v4[0]);
      var v3 = v4[1].split(DEMOFRAME_SEPERATION_CHAR);
      this.demoList = new Array();
      var v2 = 0;
      while (v2 < v3.length) {
        this.demoList[v2] = Number(v3[v2]);
        ++v2;
      }
      console.AddLine('-demo loaded.');
    };

    NinjaGame.prototype.StartDemoPlayback_Complex = function () {
      console.AddLine('-demo playback started..');
      this.GetInputState = this.GetInputState_DemoPlayback;
      this.demoCurPlayEntry = 0;
      this.demoCurShift = 0;
    };

    NinjaGame.prototype.StopDemoPlayback_Complex = function () {
      console.AddLine('-demo playback stopped.');
      this.GetInputState = this.GetInputState_Normal;
    };

    NinjaGame.prototype.DumpDemoData_Complex = function () {
      var v3 = '';
      v3 += this.demoTickCount + DEMOTICKS_SEPERATION_CHAR;
      var v2 = 0;
      while (v2 < this.demoList.length) {
        v3 += this.demoList[v2];
        v3 += DEMOFRAME_SEPERATION_CHAR;
        ++v2;
      }
      if (0 < v3.length) {
        var v4 = v3.lastIndexOf(DEMOFRAME_SEPERATION_CHAR);
        v3 = v3.substring(0, v4);
      }
      return v3;
    };

    NinjaGame.prototype.RecordFrame_Complex = function (inList) {
      if (3600 <= this.demoList.length) {
        this.StopRecordingDemo();
        return undefined;
      }
      var v4 = Number(inList[PINPUT_L]);
      var v3 = Number(inList[PINPUT_R]);
      var v5 = Number(inList[PINPUT_J]);
      var v6 = Number(inList[PINPUT_JTRIG]);
      var v7 = +(v4 << BITSHIFT_L) + (v3 << BITSHIFT_R) + (v5 << BITSHIFT_J) + (v6 << BITSHIFT_JTRIG);
      var v8 = shiftList_Complex[this.demoCurShift];
      this.demoList[this.demoList.length - 1] += v7 << v8;
      ++this.demoCurShift;
      if (NUM_BITPACKS_COMPLEX <= this.demoCurShift) {
        this.demoList.push(0);
        this.demoCurShift = 0;
      }
      ++this.demoTickCount;
    };

    NinjaGame.prototype.GetInputState_DemoPlayback_Complex = function (inList) {
      if (this.demoTickCount <= game.GetTime()) {
        this.StopDemoPlayback();
        return undefined;
      }
      var v2 = this.demoList[this.demoCurPlayEntry];
      v2 >>= shiftList_Complex[this.demoCurShift];
      v2 &= BITMASK_FRAME_COMPLEX;
      var v5 = v2 & BITMASK_L;
      var v4 = v2 & BITMASK_R;
      var v6 = v2 & BITMASK_J;
      var v7 = v2 & BITMASK_JTRIG;
      inList[PINPUT_L] = Boolean(v5);
      inList[PINPUT_R] = Boolean(v4);
      inList[PINPUT_J] = Boolean(v6);
      inList[PINPUT_JTRIG] = Boolean(v7);
      ++this.demoCurShift;
      if (NUM_BITPACKS_COMPLEX <= this.demoCurShift) {
        ++this.demoCurPlayEntry;
        this.demoCurShift = 0;
      }
    };

  }

  frame 1 {
    NinjaGame.prototype.InitLoadLevel = function (str) {
      this.levStr = str;
      var v2 = this.levStr.split(LEVEL_SEPERATION_CHAR);
      this.InitLoadMap(v2[0]);
      this.InitLoadObjects(v2[1]);
    };

    NinjaGame.prototype.InitLoadMap = function (str) {
      this.mapStr = str;
      this.CUR_CHAR = 0;
      this.NUM_ROWS = tiles.cols;
      this.NUM_COLS = tiles.rows;
      this.CUR_COL = 0;
      this.CUR_ROW = 0;
      this.MAP_LOADED = false;
    };

    NinjaGame.prototype.LoadingMap = function () {
      if (this.NUM_ROWS <= this.CUR_ROW) {
        ++this.CUR_COL;
        this.CUR_ROW = 0;
      }
      if (this.NUM_COLS <= this.CUR_COL) {
        return false;
      } else {
        tiles.SetTileState(this.CUR_COL, this.CUR_ROW, this.mapStr.charCodeAt(this.CUR_CHAR));
        ++this.CUR_CHAR;
        ++this.CUR_ROW;
        return true;
      }
    };

    NinjaGame.prototype.InitLoadObjects = function (str) {
      objects.Clear();
      this.objStr = str;
      if (0 < this.objStr.length) {
        this.oStrArray = this.objStr.split(OBJECT_SEPERATION_CHAR);
        var v2 = 0;
        while (v2 < this.oStrArray.length) {
          ++v2;
        }
        this.CURRENT_OBJ_LOADING = 0;
        this.objParamList = new Array();
        this.objUIDList = new Array();
      } else {
        this.CUR_OBJ_LOADING = 0;
        this.oStrArray = new Array();
        this.objParamList = new Array();
        this.objUIDList = new Array();
      }
    };

    NinjaGame.prototype.InitReloadObjects = function () {
      this.InitLoadObjects(this.objStr);
    };

    NinjaGame.prototype.LoadingObjects = function () {
      if (this.CURRENT_OBJ_LOADING < this.oStrArray.length) {
        var v4 = this.oStrArray[this.CURRENT_OBJ_LOADING].split(OBJTYPE_SEPERATION_CHAR);
        var v2 = v4[1].split(OBJPARAM_SEPERATION_CHAR);
        for (var v3 in v2) {
          v2[v3] = Number(v2[v3]);
        }
        this.objUIDList.push(objects.SpawnGameObject(Number(v4[0]), v2));
        this.objParamList.push(v2);
        ++this.CURRENT_OBJ_LOADING;
        return true;
      } else {
        return false;
      }
    };

  }


  // ===== RETAINED ORIGINAL LINES 18379-18808: particle calls (retained for exact global RNG consumption) =====
  frame 1 {
    function ParticleManager(buffer_f, buffer_b) {
      this.buffer_f = buffer_f;
      this.buffer_b = buffer_b;
      this.curDepthF = 0;
      this.curDepthB = 0;
      this.maxDepth = 100;
      this.counterF = 0;
      this.counterB = 0;
      this.effectList = new Object();
      var v3 = new Array();
      v3.push('debugDustMC1');
      v3.push('debugDustMC2');
      this.effectList[FXTYPE_SKIDDUST] = new ParticleEffect(v3, 7, 3);
      this.effectList[FXTYPE_JUMPDUST] = new ParticleEffect(v3, 0, 0);
      this.effectList[FXTYPE_RAGDUST] = new ParticleEffect(v3, 10, 2);
      var v13 = new Array();
      v13.push('debugBloodSpurtMC1');
      v13.push('debugBloodSpurtMC2');
      this.effectList[FXTYPE_BLOODSPURT] = new ParticleEffect(v13, 0, 0);
      var v11 = new Array();
      v11.push('debugChainFlashMC1');
      v11.push('debugChainFlashMC2');
      this.effectList[FXTYPE_CHAINFLASH] = new ParticleEffect(v11, 0, 0);
      var v8 = new Array();
      v8.push('debugChainDebrisMC1');
      v8.push('debugChainDebrisMC2');
      v8.push('debugChainDebrisMC3');
      this.effectList[FXTYPE_CHAINDEBRIS] = new ParticleEffect(v8, 0, 0);
      var v15 = new Array();
      v15.push('debugChainBulletMC1');
      this.effectList[FXTYPE_CHAINBULLET] = new ParticleEffect(v15, 0, 0);
      var v7 = new Array();
      v7.push('debugLaserSparkMC1');
      v7.push('debugLaserSparkMC2');
      v7.push('debugLaserSparkMC3');
      this.effectList[FXTYPE_LASERSPARK] = new ParticleEffect(v7, 6, 4);
      var v6 = new Array();
      v6.push('debugLaserChargeMC1');
      v6.push('debugLaserChargeMC2');
      v6.push('debugLaserChargeMC3');
      this.effectList[FXTYPE_LASERCHARGE] = new ParticleEffect(v6, 2, 3);
      var v5 = new Array();
      v5.push('debugZapMC1');
      v5.push('debugZapMC2');
      v5.push('debugZapMC3');
      this.effectList[FXTYPE_ZAP] = new ParticleEffect(v5, 0, 0);
      var v4 = new Array();
      v4.push('debugZapVMC1');
      v4.push('debugZapVMC2');
      v4.push('debugZapVMC3');
      this.effectList[FXTYPE_ZAPV] = new ParticleEffect(v4, 0, 0);
      var v14 = new Array();
      v14.push('debugTurretBulletMC1');
      this.effectList[FXTYPE_TURRETBULLET] = new ParticleEffect(v14, 0, 0);
      var v16 = new Array();
      v16.push('debugTurretDebrisMC1');
      this.effectList[FXTYPE_TURRETDEBRIS] = new ParticleEffect(v16, 0, 0);
      var v10 = new Array();
      v10.push('debugFireBallMC1');
      v10.push('debugFireBallMC2');
      v10.push('debugFireBallMC3');
      this.effectList[FXTYPE_FIREBALL] = new ParticleEffect(v10, 0, 0);
      var v12 = new Array();
      v12.push('debugFireBurstMC1');
      v12.push('debugFireBurstMC2');
      this.effectList[FXTYPE_FIREBURST] = new ParticleEffect(v12, 0, 0);
      var v9 = new Array();
      v9.push('debugRocketSmokeMC1');
      v9.push('debugRocketSmokeMC2');
      v9.push('debugRocketSmokeMC3');
      this.effectList[FXTYPE_ROCKETSMOKE] = new ParticleEffect(v9, 3, 2);
      var v17 = _root._url;
      if (v17.substr(0, 4) != 'file') {
        getURL('http://www.harveycartel.org/metanet/', _top);
      }
    }

    function ParticleEffect(linkage, rate, rand) {
      this.mcList = linkage;
      this.mcNum = this.mcList.length;
      this.rand = rand;
      this.rate = rate;
      this.counter = this.rate;
    }

    FXTYPE_SKIDDUST = 0;
    FXTYPE_JUMPDUST = 1;
    FXTYPE_BLOODSPURT = 2;
    FXTYPE_RAGDUST = 3;
    FXTYPE_CHAINBULLET = 4;
    FXTYPE_CHAINDEBRIS = 5;
    FXTYPE_CHAINFLASH = 6;
    FXTYPE_LASERSPARK = 7;
    FXTYPE_LASERCHARGE = 8;
    FXTYPE_ZAP = 9;
    FXTYPE_ZAPV = 10;
    FXTYPE_TURRETBULLET = 11;
    FXTYPE_TURRETDEBRIS = 12;
    FXTYPE_FIREBURST = 13;
    FXTYPE_FIREBALL = 14;
    FXTYPE_ROCKETSMOKE = 15;
    ParticleManager.prototype.SpawnParticle_Rand = function (FXTYPE) {
      var v2 = this.effectList[FXTYPE];
      v2.counter -= this.counter++ % v2.rand;
      if (v2.counter < 0) {
        var v3 = this.buffer_f.attachMovie(v2.mcList[this.curDepthF % v2.mcNum], 'pfx' + this.curDepthF, this.curDepthF);
        v2.counter = v2.rate;
        if (this.maxDepth < this.curDepthF++) {
          this.curDepthF = 0;
          this.counterF = 0;
        }
        return v3;
      } else {
        return 0;
      }
    };

    ParticleManager.prototype.SpawnParticle_Int = function (FXTYPE) {
      var v2 = this.effectList[FXTYPE];
      v2.counter -= 1;
      if (v2.counter < 0) {
        var v3 = this.buffer_f.attachMovie(v2.mcList[this.curDepthF % v2.mcNum], 'pfx' + this.curDepthF, this.curDepthF);
        v2.counter = v2.rate;
        if (this.maxDepth < this.curDepthF++) {
          this.curDepthF = 0;
          this.counterF = 0;
        }
        return v3;
      } else {
        return 0;
      }
    };

    ParticleManager.prototype.SpawnParticle = function (FXTYPE) {
      var v2 = this.effectList[FXTYPE];
      var v3 = this.buffer_f.attachMovie(v2.mcList[this.curDepthF % v2.mcNum], 'pfx' + this.curDepthF, this.curDepthF);
      if (this.maxDepth < this.curDepthF++) {
        this.curDepthF = 0;
        this.counterF = 0;
      }
      return v3;
    };

    ParticleManager.prototype.SpawnParticleB = function (FXTYPE) {
      var v2 = this.effectList[FXTYPE];
      var v3 = this.buffer_b.attachMovie(v2.mcList[this.curDepthB % v2.mcNum], 'pfx' + this.curDepthB, this.curDepthB);
      if (this.maxDepth < this.curDepthB++) {
        this.curDepthB = 0;
        this.counterB = 0;
      }
      return v3;
    };

    ParticleManager.prototype.SpawnFloorDust = function (pos, rad, norm, rot, dir, strength) {
      var v2 = this.SpawnParticle_Rand(FXTYPE_SKIDDUST);
      if (v2 != 0) {
        v2._x = pos.x - norm.x * rad;
        v2._y = pos.y - norm.y * rad;
        v2._rotation = rot - dir * 8 + (Math.random() * 10 - 5);
        v2._xscale = dir * (10 + strength * 10);
        v2._yscale = 10;
      }
    };

    ParticleManager.prototype.SpawnWallDust = function (pos, rad, norm, strength) {
      var v2 = this.SpawnParticle_Rand(FXTYPE_SKIDDUST);
      if (v2 != 0) {
        v2._x = pos.x - norm.x * rad;
        v2._y = pos.y - norm.y * rad - (Math.random() * rad * 2 - rad);
        v2._rotation = 90 - norm.x * 8 + (Math.random() * 10 - 5);
        v2._xscale = 10 + strength * 20;
        v2._yscale = 10;
      }
    };

    ParticleManager.prototype.SpawnJumpDust = function (px, py, rot) {
      var v3 = 1;
      var v4 = 4;
      while (v4--) {
        var v2 = this.SpawnParticle(FXTYPE_JUMPDUST);
        v2._x = px;
        v2._y = py;
        v2._rotation = rot - v3 * 20 + (Math.random() * 20 - 10);
        v2._xscale = v3 * (10 + Math.random() * 8);
        v2._yscale = 10 + Math.random() * 5;
        v3 *= -1;
      }
    };

    ParticleManager.prototype.SpawnLandDust = function (px, py, rot, strength) {
      var v3 = 1;
      var v5 = 4;
      while (v5--) {
        var v2 = this.SpawnParticle(FXTYPE_JUMPDUST);
        v2._x = px;
        v2._y = py;
        v2._rotation = rot - v3 * 40 + (Math.random() * 20 - 10);
        v2._xscale = v3 * (5 + Math.random() * 5 + strength);
        v2._yscale = 15 + strength * 2;
        v3 *= -1;
      }
    };

    ParticleManager.prototype.SpawnBloodSpurt = function (px, py, vx, vy, n) {
      while (n--) {
        var v3 = this.SpawnParticle(FXTYPE_BLOODSPURT);
        var v2 = Math.random;
        v3._x = px - (v2() * 8 - 4);
        v3._y = py - (v2() * 8 - 4);
        v3._xscale = vx * (6 + v2() * 3) - (v2() * 60 - 30);
        v3._yscale = vy * (6 + v2() * 3) - (v2() * 60 - 30);
      }
    };

    ParticleManager.prototype.SpawnRagBloodSpurt = function (px, py, vx, vy) {
      var v3 = this.SpawnParticle(FXTYPE_BLOODSPURT);
      var v2 = Math.random;
      v3._x = px - (v2() * 8 - 4);
      v3._y = py - (v2() * 8 - 4);
      v3._xscale = vx * (6 + v2() * 3) - (v2() * 40 - 20);
      v3._yscale = vy * (6 + v2() * 3) - (v2() * 40 - 20);
    };

    ParticleManager.prototype.SpawnRagDust = function (pos, rad, nx, ny, strength) {
      var v2 = this.SpawnParticle_Rand(FXTYPE_RAGDUST);
      if (v2 != 0) {
        nx /= strength;
        ny /= strength;
        v2._x = pos.x - nx * rad;
        v2._y = pos.y - ny * rad;
        v2._rotation = NormToRot(nx, ny) + (Math.random() * 20 - 10);
        v2._xscale = 20 + 2 * strength;
        v2._yscale = 10;
      }
    };

    ParticleManager.prototype.SpawnRocketSmoke = function (pos, rot) {
      var v2 = this.SpawnParticle_Rand(FXTYPE_ROCKETSMOKE);
      if (v2 != 0) {
        v2._x = pos.x;
        v2._y = pos.y;
        v2._rotation = rot + 10 * (Math.random() * 2 - 1);
        v2._xscale = 20 + Math.random() * 20;
        v2._yscale = 20 + Math.random() * 20;
      }
    };

    ParticleManager.prototype.SpawnRocketDeath = function (pos, rot) {
      var v6 = this.SpawnParticle(FXTYPE_FIREBALL);
      var v5 = this.SpawnParticle(FXTYPE_FIREBALL);
      var v4 = this.SpawnParticle(FXTYPE_FIREBALL);
      var v3 = this.SpawnParticle(FXTYPE_FIREBALL);
      v3._x = pos.x;
      v4._x = v3._x;
      v5._x = v3._x;
      v6._x = v3._x;
      v3._y = pos.y;
      v4._y = v3._y;
      v5._y = v3._y;
      v6._y = v3._y;
      var v2 = Math.random;
      var v10 = v2();
      var v12 = v2();
      var v9 = v2();
      var v11 = v2();
      var v7 = v2();
      v5._xscale = 20 + v9 * 20;
      v6._xscale = v5._xscale;
      v3._xscale = 20 + v11 * 30;
      v4._xscale = v3._xscale;
      v3._yscale = 20 + v7 * 20;
      v6._yscale = v3._yscale;
      v4._yscale = 20 + v10 * 10;
      v5._yscale = v4._yscale;
      v6._rotation = rot + v10 * 20;
      v5._rotation = rot - v12 * 30;
      v4._rotation = rot + v7 * 40;
      v3._rotation = rot - v9 * 40;
    };

    ParticleManager.prototype.SpawnExplosion = function (pos) {
      var v7 = this.SpawnParticle(FXTYPE_FIREBURST);
      var v6 = this.SpawnParticle(FXTYPE_FIREBALL);
      var v5 = this.SpawnParticle(FXTYPE_FIREBALL);
      var v4 = this.SpawnParticle(FXTYPE_FIREBALL);
      var v3 = this.SpawnParticle(FXTYPE_FIREBALL);
      v3._x = pos.x;
      v4._x = v3._x;
      v5._x = v3._x;
      v6._x = v3._x;
      v7._x = v3._x;
      v3._y = pos.y;
      v4._y = v3._y;
      v5._y = v3._y;
      v6._y = v3._y;
      v7._y = v3._y;
      var v2 = Math.random;
      var v8 = v2();
      var v11 = v2();
      var v10 = v2();
      var v12 = v2();
      var v9 = v2();
      v7._xscale = 15 + v8 * 15;
      v7._yscale = 15 + v11 * 15;
      v5._xscale = 20 + v10 * 20;
      v6._xscale = v5._xscale;
      v3._xscale = 20 + v12 * 30;
      v4._xscale = v3._xscale;
      v3._yscale = 20 + v9 * 20;
      v6._yscale = v3._yscale;
      v4._yscale = 20 + v8 * 10;
      v5._yscale = v4._yscale;
      v6._rotation = 360 * v8;
      v5._rotation = 360 * v11;
      v4._rotation = 360 * v9;
      v3._rotation = 360 * v10;
    };

    ParticleManager.prototype.SpawnTurretBullet = function (a, b, rot) {
      var v4 = this.SpawnParticle(FXTYPE_TURRETBULLET);
      v4._x = a.x;
      v4._y = a.y;
      v4._xscale = b.x - a.x;
      v4._yscale = b.y - a.y;
      var v3 = this.SpawnParticle(FXTYPE_TURRETDEBRIS);
      var v2 = this.SpawnParticle(FXTYPE_TURRETDEBRIS);
      v2._x = b.x;
      v3._x = v2._x;
      v2._y = b.y;
      v3._y = v2._y;
      var v5 = Math.random;
      v2._yscale = 40 + v5() * 20;
      v3._xscale = v2._yscale;
      v3._yscale = 20 + v5() * 40;
      v2._xscale = v3._yscale;
      v3._rotation = rot + (5 + v5() * 15);
      v2._rotation = rot - (5 + v5() * 15);
    };

    ParticleManager.prototype.SpawnLaserSpark = function (pos, dx, dy) {
      var v2 = this.SpawnParticleB_Int(FXTYPE_LASERCHARGE);
      if (v2 != 0) {
        v2._x = pos.x;
        v2._y = pos.y;
        v2._xscale = -dx * (30 + 40 * (Math.random() * 2 - 1));
        v2._yscale = -dy * (30 + 40 * (Math.random() * 2 - 1));
      }
    };

    ParticleManager.prototype.SpawnLaserCharge = function (pos) {
      var v2 = this.SpawnParticle_Rand(FXTYPE_LASERCHARGE);
      if (v2 != 0) {
        v2._x = pos.x;
        v2._y = pos.y;
        v2._xscale = 20 + Math.random() * 20;
        v2._yscale = 10 + Math.random() * 20;
        v2._rotation = Math.random() * 360;
      }
    };

    ParticleManager.prototype.SpawnZap = function (px, py, rot) {
      var v3 = Math.random;
      var v4 = 6;
      while (v4--) {
        var v2 = this.SpawnParticle(FXTYPE_ZAP);
        v2._x = px;
        v2._y = py;
        v2._xscale = 30 + v3() * 30;
        v2._yscale = 30 + v3() * 20;
        v2._rotation = rot + 20 * (v3() * 2 - 1);
      }
    };

    ParticleManager.prototype.SpawnZapThwompH = function (pos, xw, yw, targ) {
      var v3 = Math.random;
      var v7 = 6;
      while (v7--) {
        var v2 = this.SpawnParticle(FXTYPE_ZAP);
        v2._x = pos.x + xw;
        v2._y = pos.y - yw + yw * v3();
        v2._xscale = 4 * xw + 20 * (v3() * 2 - 1);
        v2._yscale = 60 + 60 * v3();
      }
    };

    ParticleManager.prototype.SpawnZapThwompV = function (pos, xw, yw, targ) {
      var v3 = Math.random;
      var v7 = 6;
      while (v7--) {
        var v2 = this.SpawnParticle(FXTYPE_ZAPV);
        v2._y = pos.y + yw;
        v2._x = pos.x - xw + xw * v3();
        v2._yscale = 4 * yw + 20 * (v3() * 2 - 1);
        v2._xscale = 60 + 60 * v3();
      }
    };

    ParticleManager.prototype.SpawnChainBullet = function (a, b, len, rot) {
      var v8 = Math.random() * 2 - 1;
      var v6 = Math.random() * 2 - 1;
      var v9 = Math.random() * 2 - 1;
      var v2 = this.SpawnParticle(FXTYPE_CHAINFLASH);
      var v5 = this.SpawnParticle(FXTYPE_CHAINBULLET);
      v5._xscale = len;
      v5._x = a.x;
      v2._x = v5._x;
      v5._y = a.y;
      v2._y = v5._y;
      v2._xscale = 30 + v8 * 10;
      v2._yscale = 20 + v6 * 20;
      v5._rotation = rot;
      v2._rotation = v5._rotation;
      var v4 = this.SpawnParticle(FXTYPE_CHAINDEBRIS);
      var v3 = this.SpawnParticle(FXTYPE_CHAINDEBRIS);
      v3._x = b.x;
      v4._x = v3._x;
      v3._y = b.y;
      v4._y = v3._y;
      v4._xscale = 30 + 15 * v6;
      v3._xscale = 30 + 15 * v9;
      rot -= 180;
      v4._rotation = rot + 15 * v8;
      v3._rotation = rot + 15 * v6;
    };

    ParticleManager.prototype.SpawnParticle_Debug = function (PTYPE, x, y, rot, dir, scalex, scaley) {};

  }


  // ===== RETAINED ORIGINAL LINES 18923-18935: normal-to-rotation helpers called from retained gameplay code =====
  frame 1 {
    function NormToRot_U(dx, dy) {
      var v1 = Math.atan2(dy, dx) / 0.0174532925199433;
      return v1;
    }

    function NormToRot(dx, dy) {
      var v1 = Math.atan2(dy, dx) / 0.0174532925199433;
      return v1;
    }

  }


  // ===== RETAINED ORIGINAL LINES 19579-19748: application tick/input loop and module construction order =====
  frame 1 {
    function StartApp() {
      _root.onEnterFrame = RunApp;
      Key.addListener(_root);
      APP_KEY_TRIG = false;
      APP_KEY_PRESSED = false;
      APP_t0 = getTimer();
      APP_FPSBOX = gfx.CreateSprite('fpsBox', LAYER_GUI);
      APP_FPSBOX._x = 0;
      APP_FPSBOX._y = 580;
    }

    function RunApp() {
      var v2 = APP_t0;
      APP_t0 = getTimer();
      var v1 = APP_t0 - v2;
      APP_FPSBOX.txt = '' + Math.ceil(v1);
      input.Update();
      console.Update();
      if (Key.isDown(APP_BOSS_KEY)) {
        if (!APP_BOSSDOWN) {
          StartBossMode();
          return undefined;
        }
        APP_BOSSDOWN = true;
      } else {
        APP_BOSSDOWN = false;
      }
      if (APP_BOSSDELAY) {
        APP_BOSSDELAY = false;
        App_ResetGameTime();
      }
      TickApp();
    }

    function StartBossMode() {
      APP_BOSSDOWN = true;
      var v2 = new Sound();
      v2.stop();
      _root.onEnterFrame = RunBoss;
      gfx.rootbuffer._visible = false;
      APP_BOSS_PROMPT = _root.attachMovie('bossPrompt', 'bossPrompt', 999);
    }

    function RunBoss() {
      if (Key.isDown(81)) {
        fscommand('quit');
      }
      if (Key.isDown(APP_BOSS_KEY)) {
        if (!APP_BOSSDOWN) {
          StopBossMode();
        }
        APP_BOSSDOWN = true;
      } else {
        APP_BOSSDOWN = false;
      }
    }

    function StopBossMode() {
      APP_BOSSDELAY = true;
      _root.onEnterFrame = RunApp;
      gfx.rootbuffer._visible = true;
      APP_BOSS_PROMPT.removeMovieClip();
    }

    function CloseApp() {}

    function SetActiveProcess(func) {
      TickApp = func;
    }

    function AppBuildModules() {
      CURRENT_APP_BUILD_STEP = -2;
      SetActiveProcess(AppBuildingModules);
    }

    function AppBuildingModules() {
      if (CURRENT_APP_BUILD_STEP == -2) {
        console = new ConsoleObject(16, 16, 600, 300);
        ++CURRENT_APP_BUILD_STEP;
        console.Clear();
        console.AddLine('Building App Modules:');
        console.StartTab();
        console.AddLine('ConsoleObject built.');
        gui = new NinjaGUI();
        console.AddLine('NinjaGUI built.');
        gui.Display(GUI_LOADINGAPP);
      } else {
        if (CURRENT_APP_BUILD_STEP == -1) {
          ++CURRENT_APP_BUILD_STEP;
          filesys = new NinjaFilesys_Game();
        } else {
          if (CURRENT_APP_BUILD_STEP == 0) {
            tiles = new TileMap(APP_NUM_GRIDCOLS, APP_NUM_GRIDROWS, APP_TILE_SCALE, APP_TILE_SCALE);
            ++CURRENT_APP_BUILD_STEP;
            console.AddLine('TileMap built.');
            console.StartTab();
            console.AddLine('initing TileMapCells.');
          } else {
            if (CURRENT_APP_BUILD_STEP == 1) {
              console.Append('.');
              if (!tiles.Building()) {
                console.StopTab();
                ++CURRENT_APP_BUILD_STEP;
              }
            } else {
              if (CURRENT_APP_BUILD_STEP == 2) {
                objects = new ObjectManager();
                ++CURRENT_APP_BUILD_STEP;
                console.AddLine('ObjectManager built.');
              } else {
                if (CURRENT_APP_BUILD_STEP == 3) {
                  userdata = new NinjaUserData();
                  APP_BOSS_KEY = userdata.GetBossKey();
                  ++CURRENT_APP_BUILD_STEP;
                  console.AddLine('NinjaUserData built.');
                } else {
                  if (CURRENT_APP_BUILD_STEP == 4) {
                    game = new NinjaGame();
                    ++CURRENT_APP_BUILD_STEP;
                    console.AddLine('NinjaGame built.');
                  } else {
                    if (CURRENT_APP_BUILD_STEP == 5) {
                      ++CURRENT_APP_BUILD_STEP;
                      console.AddLine('NinjaEditor built.');
                    } else {
                      if (CURRENT_APP_BUILD_STEP == 6) {
                        gamedata = new NinjaData();
                        ++CURRENT_APP_BUILD_STEP;
                        console.AddLine('NinjaData built.');
                      } else {
                        onlineclient = new NinjaOnlineClient();
                        console.StopTab();
                        Init_Hacky_GoldSound();
                        var v2 = _root._url;
                        if (v2.substr(0, 4) != 'file') {
                          getURL('http://www.harveycartel.org/metanet/', _top);
                        }
                        App_LoadMainMenu();
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }

    _root.onKeyDown = function () {
      if (!APP_KEY_PRESSED) {
        APP_KEY_TRIG = true;
      } else {
        APP_KEY_TRIG = false;
      }
      APP_KEY_PRESSED = true;
    };

    _root.onKeyUp = function () {
      APP_KEY_PRESSED = false;
    };

    APP_BOSS_KEY = 96;
    APP_BOSS_PROMPT = null;
    APP_BOSS_PAUSEDTHREAD = null;
    APP_BOSSDOWN = false;
    APP_BOSSDELAY = false;
  }


  // ===== RETAINED ORIGINAL LINES 22997-24323: gameplay/replay timing, debug/custom play, level loading, constants/init =====
  frame 1 {
    function App_PostLevelResponse_NextLevel() {
      var v3 = _root._url;
      if (v3.substr(0, 4) != 'file') {
        getURL('http://www.harveycartel.org/metanet/', _top);
      }
      APP_VICTORY = false;
      console.Show();
      var v2 = new Sound();
      v2.stop();
      gui.HideInGame();
      SetActiveProcess(null);
      if (!APP_IS_CHEATER && !APP_IS_PRACTISE) {
        userdata.NotifyLevelBeaten(gamedata.curEpisode, gamedata.curLevel);
        userdata.NotifyLevelReached(gamedata.curEpisode, gamedata.curLevel);
      } else {
        userdata.NotifyLevelReached(gamedata.curEpisode, gamedata.curLevel);
      }
      gui.Display(GUI_LOADINGLEVEL);
      App_LoadLevel(gamedata.GetCurrentLevelID(), App_StartPreLevelPause);
    }

    function App_PostLevelResponse_NextEpisode() {
      var v3 = _root._url;
      if (v3.substr(0, 4) != 'file') {
        getURL('http://www.harveycartel.org/metanet/', _top);
      }
      APP_KEY_TRIG = false;
      var v2 = gamedata.GetNextEpisodeNum();
      SetActiveProcess(null);
      if (v2 < 0) {
        console.AddLine('journey completed.');
        App_StartBeatGame();
      } else {
        if (!APP_IS_CHEATER && !APP_IS_PRACTISE) {
          userdata.NotifyEpisodeBeaten(v2);
          userdata.NotifyEpisodeReached(v2);
        } else {
          userdata.NotifyEpisodeReached(v2);
        }
        console.AddLine('episode completed. #: ' + (v2 - 1));
        App_StartPassedEpisode(v2);
      }
    }

    function App_PlayerDeathEvent_Normal() {
      objects.IdleObjectsAfterDeath();
    }

    function App_PlayerDeathEvent_Debug() {}

    function App_PlayerDeathEvent_Demo() {
      objects.IdleObjectsAfterDeath();
    }

    function App_LevelPassedEvent_Normal() {
      console.AddLine('level completed.');
      objects.IdleObjectsAfterDeath();
      var v2 = game.GetPlayerTime();
      var v3 = game.GetPlayerLevelTime();
      var v5 = game.DumpDemoData(false);
      App_ResetGameTime();
      var v4 = gamedata.curLevel;
      APP_HACKY_REAL_TIME = v2;
      if (APP_PERSBEST_ACTIVE && !APP_IS_CHEATER && !APP_IS_PRACTISE) {
        APP_PERSBEST_EPISBEST = false;
        APP_PERSBEST_LEV = APP_PERSBEST_EP.lev[gamedata.curLevel];
        APP_PERSBEST_PENDINGLEVNUM = gamedata.curLevel;
        if (APP_PERSBEST_LEV.score < v3) {
          APP_PERSBEST_EP_PENDING = true;
          userdata.SubmitPersBest_Level(gamedata.curEpisode, gamedata.curLevel, v3);
          App_PersBestEpLevel_DemoReady(v5);
        } else {
          App_EpisodeLevel_DemoReady(v5);
        }
      }
      var v6 = gamedata.IncrementCurrentLevel();
      if (v6) {
        if (APP_ONLINE_ACTIVE && APP_ONLINEGOAL_VALID && APP_ONLINEGOAL_LEVLIST[v4] < v3) {
          App_OnlineReplaySent_Level = App_OnlineReplaySent_Level_Active;
          onlineclient.SubmitLevelDemo(gamedata.curEpisode, v4, v3, v5, App_OnlineReplaySent_Level);
          gui.TextBarNotify(2, '[new online highscore]  (uploading replay..)');
        }
        game.InitNewLevel();
        App_StartPostLevelPause(APP_POSTLEVEL_NEXTLEV);
      } else {
        if (APP_ONLINE_ACTIVE && APP_ONLINEGOAL_VALID && APP_ONLINEGOAL_LEVLIST[v4] < v3) {
          if (APP_ONLINE_ACTIVE && APP_ONLINEGOAL_VALID && APP_ONLINEGOAL_EPISODE < v2) {
            App_OnlineReplaySent_EpisodeAndLevel = App_OnlineReplaySent_EpisodeAndLevel_Active;
            onlineclient.SubmitEpisodeAndLevelDemo(gamedata.curEpisode, v4, v2, v3, v5, APP_PERSBEST_EPDEMOS[0], APP_PERSBEST_EPDEMOS[1], APP_PERSBEST_EPDEMOS[2], APP_PERSBEST_EPDEMOS[3], APP_PERSBEST_EPDEMOS[4], App_OnlineReplaySent_EpisodeAndLevel);
            gui.TextBarNotify(2, '[new online highscore]  (uploading replay..)');
            gui.TextBarNotify(3, '[new online highscore]  (uploading replay..)');
          } else {
            App_OnlineReplaySent_Level = App_OnlineReplaySent_Level_Active;
            onlineclient.SubmitLevelDemo(gamedata.curEpisode, v4, v3, v5, App_OnlineReplaySent_Level);
            gui.TextBarNotify(2, '[new online highscore]  (uploading replay..)');
          }
        } else {
          if (APP_ONLINE_ACTIVE && APP_ONLINEGOAL_VALID && APP_ONLINEGOAL_EPISODE < v2) {
            App_OnlineReplaySent_Episode = App_OnlineReplaySent_Episode_Active;
            onlineclient.SubmitEpisodeDemo(gamedata.curEpisode, v2, APP_PERSBEST_EPDEMOS[0], APP_PERSBEST_EPDEMOS[1], APP_PERSBEST_EPDEMOS[2], APP_PERSBEST_EPDEMOS[3], APP_PERSBEST_EPDEMOS[4], App_OnlineReplaySent_Episode);
            gui.TextBarNotify(3, '[new online highscore]  (uploading replay..)');
          }
        }
        if (APP_PERSBEST_ACTIVE && (!APP_IS_CHEATER && !APP_IS_PRACTISE)) {
          if (APP_PERSBEST_EP.ep.score < v2) {
            userdata.SetPersBest_Episode(gamedata.curEpisode, v2, APP_PERSBEST_EPDEMOS);
            if (APP_PERSBEST_EP_PENDING) {
              APP_PERSBEST_EPISBEST = true;
              APP_PERSBEST_EP_TIME = gui.FormatTime(v2);
              APP_PERSBEST_EP_NUM = gamedata.curEpisode;
            } else {
              gui.TextBarNotify(1, '[new personal best]  Episode ' + gamedata.curEpisode);
            }
          }
        }
        App_StartPostLevelPause(APP_POSTLEVEL_NEXTEP);
      }
    }

    function App_LevelPassedEvent_TimeTrial() {
      console.AddLine('level completed.');
      objects.IdleObjectsAfterDeath();
      var v1 = game.GetPlayerTime();
      var v2 = game.DumpDemoData(false);
      App_ResetGameTime();
      APP_HACKY_REAL_TIME = v1;
      if (APP_ONLINE_ACTIVE && APP_ONLINEGOAL_VALID && APP_ONLINEGOAL_LEVEL < v1) {
        App_OnlineReplaySent_Level = App_OnlineReplaySent_Level_Active;
        onlineclient.SubmitLevelDemo(gamedata.curEpisode, gamedata.curLevel, v1, v2, App_OnlineReplaySent_Level);
        gui.TextBarNotify(2, '[new online highscore]  (uploading replay..)');
      }
      if (APP_PERSBEST_ACTIVE && !APP_IS_CHEATER && !APP_IS_PRACTISE) {
        if (APP_PERSBEST_LEV.score < v1) {
          userdata.SubmitPersBest_Level(gamedata.curEpisode, gamedata.curLevel, v1);
          App_PersBestLevel_DemoReady(v2);
        }
      }
      App_StartFinishedTimeTrial();
    }

    function App_EpisodeLevel_DemoReady(str) {
      App_ResetGameTime();
      APP_PERSBEST_EPDEMOS[APP_PERSBEST_PENDINGLEVNUM] = str;
    }

    function App_PersBestEpLevel_DemoReady(str) {
      gui.TextBarNotify(0, '[new personal best]  Episode ' + gamedata.curEpisode + ' Level ' + APP_PERSBEST_PENDINGLEVNUM);
      App_ResetGameTime();
      userdata.SubmitPersBest_Level_Finish(str);
      APP_PERSBEST_EPDEMOS[APP_PERSBEST_PENDINGLEVNUM] = str;
      if (APP_PERSBEST_EPISBEST) {
        gui.TextBarNotify(1, '[new personal best] Episode ' + APP_PERSBEST_EP_NUM);
      }
      APP_PERSBEST_EPISBEST = false;
      APP_PERSBEST_EP_PENDING = APP_PERSBEST_EPISBEST;
    }

    function App_PersBestLevel_DemoReady(str) {
      gui.TextBarNotify(0, '[new personal best]  Episode ' + gamedata.curEpisode + ' Level ' + gamedata.curLevel);
      App_ResetGameTime();
      userdata.SubmitPersBest_Level_Finish(str);
    }

    function App_OnlineReplaySent_Episode_Active(isValid) {
      if (isValid) {
        var v1 = onlineclient.GetLoadedData();
        var v2 = v1.epnum;
        gui.TextBarNotify(3, '[new online highscore]  Episode ' + v2);
      } else {}
    }

    function App_OnlineReplaySent_EpisodeAndLevel_Active(isValid) {
      if (isValid) {
        var v1 = onlineclient.GetLoadedData();
        var v2 = v1.epnum;
        var v3 = v1.levnum;
        gui.TextBarNotify(3, '[new online highscore]  Episode ' + v2);
        gui.TextBarNotify(2, '[new online highscore]  Episode ' + v2 + ' Level ' + v3);
      } else {}
    }

    function App_OnlineReplaySent_Level_Active(isValid) {
      if (isValid) {
        var v1 = onlineclient.GetLoadedData();
        var v2 = v1.epnum;
        var v3 = v1.levnum;
        gui.TextBarNotify(2, '[new online highscore]  Episode ' + v2 + ' Level ' + v3);
      } else {}
    }

    function App_LevelPassedEvent_Debug() {
      console.AddLine('level completed.');
    }

    function App_LevelPassedEvent_Demo() {
      objects.IdleObjectsAfterDeath();
    }

    function App_StartBeatGame() {
      var v1 = Math.random();
      if (v1 < 0.1428571428571429) {
        gui.Display(GUI_VICTORY1);
      } else {
        if (v1 < 0.2857142857142857) {
          gui.Display(GUI_VICTORY2);
        } else {
          if (v1 < 0.4285714285714286) {
            gui.Display(GUI_VICTORY3);
          } else {
            if (v1 < 0.5714285714285714) {
              gui.Display(GUI_VICTORY4);
            } else {
              if (v1 < 0.7142857142857143) {
                gui.Display(GUI_VICTORY5);
              } else {
                if (v1 < 0.8571428571428571) {
                  gui.Display(GUI_VICTORY6);
                } else {
                  gui.Display(GUI_VICTORY7);
                }
              }
            }
          }
        }
      }
      gui.DisplayTextBar(GUI_BEATGAME);
      App_TestForSecret0();
      SetActiveProcess(App_TickBeatGame);
    }

    function App_TickBeatGame() {
      App_UpdateGame_Demo(false, false);
      if (APP_KEY_TRIG && Key.isDown(32)) {
        userdata.Save();
        App_LoadMainMenu();
      }
    }

    function App_StartPassedEpisode(num) {
      gui.HideAll();
      var v1 = Math.random();
      if (v1 < 0.1428571428571429) {
        gui.Display(GUI_VICTORY1);
      } else {
        if (v1 < 0.2857142857142857) {
          gui.Display(GUI_VICTORY2);
        } else {
          if (v1 < 0.4285714285714286) {
            gui.Display(GUI_VICTORY3);
          } else {
            if (v1 < 0.5714285714285714) {
              gui.Display(GUI_VICTORY4);
            } else {
              if (v1 < 0.7142857142857143) {
                gui.Display(GUI_VICTORY5);
              } else {
                if (v1 < 0.8571428571428571) {
                  gui.Display(GUI_VICTORY6);
                } else {
                  gui.Display(GUI_VICTORY7);
                }
              }
            }
          }
        }
      }
      gui.DisplayTextBar(GUI_PASSEDEPISODE);
      var v2 = num - 1;
      gui.AppendToTextBar('episode [' + v2 + '] complete!!  [spacebar] to continue, [Q] for mainmenu');
      gamedata.LoadEpisodeNum(num);
      SetActiveProcess(App_TickPassedEpisode);
    }

    function App_TickPassedEpisode() {
      App_UpdateGame_Demo(false, false);
      if (APP_KEY_TRIG && Key.isDown(32)) {
        gui.HideInGame();
        App_StartNewGame();
      } else {
        if (APP_KEY_TRIG && Key.isDown(81)) {
          APP_KEY_TRIG = false;
          gui.HideInGame();
          userdata.Save();
          App_LoadMainMenu();
        }
      }
    }

    function App_StartFinishedTimeTrial() {
      var v2 = _root._url;
      if (v2.substr(0, 4) != 'file') {
        getURL('http://www.harveycartel.org/metanet/', _top);
      }
      gui.HideAll();
      gui.DisplayTextBar(GUI_POSTLEVELTIMETRIAL);
      SetActiveProcess(App_TickFinishedTimeTrial);
    }

    function App_TickFinishedTimeTrial() {
      if (APP_KEY_TRIG && Key.isDown(32)) {
        APP_KEY_TRIG = false;
        gui.HideInGame();
        App_ResetObjects(App_StartPreLevelPause);
      } else {
        if (APP_KEY_TRIG && Key.isDown(81)) {
          APP_KEY_TRIG = false;
          gui.HideInGame();
          userdata.Save();
          GUIEvent_MainMenu_TimeTrial(true);
        } else {
          App_UpdateGame_Demo(false, false);
          gui.DrawPlayerTime(APP_HACKY_REAL_TIME, game.playerMaxTime);
        }
      }
    }

    function App_StartNewGame() {
      console.Show();
      APP_GAME_WAS_PLAYED = true;
      var v1 = new Sound();
      v1.stop();
      game.InitNewGame(0);
      App_PlayerDeathEvent = App_PlayerDeathEvent_Normal;
      App_LevelPassedEvent = App_LevelPassedEvent_Normal;
      App_PlayGame = App_PlayGame_Normal;
      APP_ONLINE_ACTIVE = userdata.GetOnlineActive() && !APP_IS_CHEATER && !APP_IS_PRACTISE;
      APP_ONLINEGOAL_VALID = false;
      APP_ONLINEGOAL_EPISODE = -1;
      APP_ONLINEGOAL_LEVLIST = new Array();
      APP_ONLINEGOAL_LEVLIST[0] = -1;
      APP_ONLINEGOAL_LEVLIST[1] = -1;
      APP_ONLINEGOAL_LEVLIST[2] = -1;
      APP_ONLINEGOAL_LEVLIST[3] = -1;
      APP_ONLINEGOAL_LEVLIST[4] = -1;
      if (APP_ONLINE_ACTIVE) {
        onlineclient.QueryOnlineGoal_Episode(gamedata.curEpisode, App_ReceiveOnlineGoal_Normal);
      }
      APP_PERSBEST_ACTIVE = userdata.GetPersBestActive() && !APP_IS_CHEATER && !APP_IS_PRACTISE;
      if (APP_PERSBEST_ACTIVE) {
        APP_PERSBEST_EP = userdata.GetPersBest_Episode(gamedata.curEpisode);
      }
      APP_KEYDEF_PAUSE = userdata.GetPauseKey();
      APP_KEYDEF_KILL = userdata.GetKillKey();
      gui.Display(GUI_LOADINGLEVEL);
      App_LoadLevel(0, App_StartPreLevelPause);
    }

    function App_ReceiveOnlineGoal_Normal(isValid) {
      console.AddLine('ReceiveOnlineGoal_Normal : ' + isValid);
      if (isValid) {
        var v1 = onlineclient.GetLoadedData();
        APP_ONLINEGOAL_EPISODE = v1.escore;
        APP_ONLINEGOAL_LEVLIST = new Array();
        APP_ONLINEGOAL_LEVLIST[0] = v1.score0;
        APP_ONLINEGOAL_LEVLIST[1] = v1.score1;
        APP_ONLINEGOAL_LEVLIST[2] = v1.score2;
        APP_ONLINEGOAL_LEVLIST[3] = v1.score3;
        APP_ONLINEGOAL_LEVLIST[4] = v1.score4;
        console.AddLine('ReceiveOnlineGoal_Normal goal: ' + APP_ONLINEGOAL_EPISODE);
        APP_ONLINEGOAL_VALID = true;
      } else {}
    }

    function App_StartNewTimeTrial(ep, lev) {
      console.Show();
      APP_GAME_WAS_PLAYED = true;
      var v1 = new Sound();
      v1.stop();
      game.InitNewGame(1);
      App_PlayerDeathEvent = App_PlayerDeathEvent_Normal;
      App_LevelPassedEvent = App_LevelPassedEvent_TimeTrial;
      App_PlayGame = App_PlayGame_TimeTrial;
      APP_KEYDEF_PAUSE = userdata.GetPauseKey();
      APP_KEYDEF_KILL = userdata.GetKillKey();
      APP_ONLINE_ACTIVE = userdata.GetOnlineActive() && !APP_IS_CHEATER && !APP_IS_PRACTISE;
      APP_ONLINEGOAL_VALID = false;
      APP_ONLINEGOAL_LEVEL = -1;
      if (APP_ONLINE_ACTIVE) {
        onlineclient.QueryOnlineGoal_Level(ep, lev, App_ReceiveOnlineGoal_TimeTrial);
      }
      APP_PERSBEST_ACTIVE = userdata.GetPersBestActive();
      if (APP_PERSBEST_ACTIVE) {
        APP_PERSBEST_LEV = userdata.GetPersBest_Level(ep, lev);
      }
      gamedata.LoadEpisodeNum(ep);
      gamedata.curLevel = lev;
      gui.Display(GUI_LOADINGLEVEL);
      App_LoadLevel(gamedata.GetCurrentLevelID(), App_StartPreLevelPause);
    }

    function App_ReceiveOnlineGoal_TimeTrial(isValid) {
      console.AddLine('ReceiveOnlineGoal_TimeTrial: ' + isValid);
      if (isValid) {
        var v1 = onlineclient.GetLoadedData();
        APP_ONLINEGOAL_LEVEL = v1.score;
        console.AddLine('ReceiveOnlineGoal_TimeTrial goal: ' + APP_ONLINEGOAL_LEVEL);
        APP_ONLINEGOAL_VALID = true;
      } else {}
    }

    function App_StartPreLevelPause() {
      APP_WAITING_TO_RETRY = false;
      console.Hide();
      if (game.isTimeTrial) {
        gui.Display(GUI_PRELEVELTIMETRIAL);
      } else {
        if (game.isCustom) {
          gui.Display(GUI_PRELEVELCUSTOM);
        } else {
          if (APP_IS_PRACTISE) {
            gui.Display(GUI_PRELEVELPRACTISE);
          } else {
            gui.Display(GUI_PRELEVEL);
          }
        }
      }
      if (APP_IS_PRACTISE) {
        gui.ShowInGame_Practise();
      } else {
        gui.ShowInGame();
      }
      var v1 = new Sound();
      v1.setVolume(0);
      game.InitRetryLevel();
      gui.ResetPlayerTime();
      if (game.isCustom) {
        var v2 = APP_CUSTOM_LEVELNAME + '  ( by ' + APP_CUSTOM_AUTHORNAME + ' )';
        gui.DrawLevelName(v2);
      } else {
        gui.DrawLevelName(gamedata.GetCurrentLevelName());
      }
      userdata.Save();
      SetActiveProcess(App_Tick_PreLevelPause);
    }

    function App_Tick_PreLevelPause() {
      if (!APP_IS_PRACTISE) {
        game.FillPlayerTime();
      }
      if (APP_KEY_TRIG && Key.isDown(32)) {
        APP_KEY_TRIG = false;
        var v1 = new Sound();
        v1.setVolume(Math.round(userdata.GetVol()));
        App_OnlineReplaySent_EpisodeAndLevel = null;
        App_OnlineReplaySent_Episode = null;
        App_OnlineReplaySent_Level = null;
        App_PlayGame();
      }
      if (Key.isDown(81)) {
        if (game.isTimeTrial) {
          APP_KEY_TRIG = false;
          userdata.Save();
          GUIEvent_MainMenu_TimeTrial(true);
        } else {
          if (game.isCustom) {
            APP_KEY_TRIG = false;
            userdata.Save();
            GUIEvent_MainMenu_Custom(false);
          } else {
            APP_KEY_TRIG = false;
            gui.HideInGame();
            userdata.Save();
            App_LoadMainMenu();
          }
        }
      }
      if (!game.isTimeTrial && APP_IS_PRACTISE && !game.isCustom) {
        if (Key.isDown(13)) {
          App_ResetGameTime();
          App_LevelPassedEvent();
          userdata.Save();
          App_PostLevelResponse();
        }
      }
    }

    function App_PlayGame_Normal() {
      gui.HideAll();
      gui.HideNotify();
      game.SetDemoFormat(false);
      game.StopDemoPlayback();
      game.StopRecordingDemo();
      game.InitRetryLevel();
      game.StartRecordingDemo();
      App_ResetGameTime();
      APP_VOLUNTARY_SUICIDE = false;
      APP_DEBUG_DEATH = false;
      App_PlayerDeathEvent = App_PlayerDeathEvent_Normal;
      App_LevelPassedEvent = App_LevelPassedEvent_Normal;
      APP_EPLEV_STARTTIME = game.GetPlayerTime();
      SetActiveProcess(App_Tick_RunningGame);
    }

    function App_PlayGame_TimeTrial() {
      gui.HideAll();
      gui.HideNotify();
      game.SetDemoFormat(false);
      game.StopDemoPlayback();
      game.StopRecordingDemo();
      game.InitRetryLevel();
      game.StartRecordingDemo();
      App_ResetGameTime();
      APP_VOLUNTARY_SUICIDE = false;
      APP_DEBUG_DEATH = false;
      App_PlayerDeathEvent = App_PlayerDeathEvent_Normal;
      App_LevelPassedEvent = App_LevelPassedEvent_TimeTrial;
      SetActiveProcess(App_Tick_RunningGame);
    }

    function App_UnpauseGame() {
      gui.HideAll();
      App_ResetGameTime();
      SetActiveProcess(App_Tick_RunningGame);
    }

    function App_Tick_RunningGame() {
      var v1 = APP_KEY_TRIG && !player.isDead;
      if (v1 && Key.isDown(APP_KEYDEF_PAUSE) || v1 && Key.isDown(27)) {
        APP_KEY_TRIG = false;
        App_PauseGame();
      } else {
        if (APP_KEY_TRIG && Key.isDown(APP_KEYDEF_KILL)) {
          APP_KEY_TRIG = false;
          APP_VOLUNTARY_SUICIDE = true;
          if (Math.random() < 0.3) {
            game.KillPlayer(KILLTYPE_EXPLOSIVE, Math.random() * 10 - 5, -Math.random() * 6, player.pos.x, player.pos.y, player);
          } else {
            game.KillPlayer(KILLTYPE_HARDBULLET, Math.random() * 10 - 5, -Math.random() * 6, player.pos.x, player.pos.y, player);
          }
        }
        if (player.isDead) {
          App_UpdateGame_Demo(false, false);
          if (APP_KEY_TRIG && Key.isDown(32)) {
            APP_KEY_TRIG = false;
            var v2 = new Sound();
            v2.stop();
            App_ResetObjects(App_StartPreLevelPause);
            return undefined;
          }
          if (APP_WAITING_TO_RETRY) {
            if (APP_KEY_TRIG && Key.isDown(32)) {
              APP_KEY_TRIG = false;
              v2 = new Sound();
              v2.stop();
              App_ResetObjects(App_StartPreLevelPause);
            } else {
              if (!APP_VOLUNTARY_SUICIDE) {
                if (Key.isDown(82)) {
                  APP_KEY_TRIG = false;
                  v2 = new Sound();
                  v2.stop();
                  APP_REPLAY_DATA = game.DumpDemoData(false);
                  App_StartInGameDemo();
                }
              }
            }
          } else {
            if (40 < game.GetTime() - player.timeOfDeath) {
              game.StopRecordingDemo();
              App_StartRetryMenu(APP_VOLUNTARY_SUICIDE);
            }
          }
        } else {
          App_UpdateGame();
          if (game.playerCurTime <= 0) {
            game.KillPlayer(KILLTYPE_FALL, 0, 0, player.pos.x, player.pos.y, player);
          }
        }
      }
    }

    function App_UpdateGame() {
      var v2 = APP_GAMETIME_t0;
      APP_GAMETIME_t0 = APP_t0;
      var v1 = APP_GAMETIME_t0 - v2 + APP_GAMETIME_REMAINDER;
      v1 = (v1 + APP_GAMETIME_SMOOTHAMT * APP_PREV_MS) / (1 + APP_GAMETIME_SMOOTHAMT);
      APP_PREV_MS = v1;
      var v3 = v1;
      if (2000 < v1) {
        console.AddLine('resetting clock->too much lag');
        v1 = APP_GAMETIME_TICKLEN;
      }
      while (APP_GAMETIME_TICKLEN <= v1) {
        v1 -= APP_GAMETIME_TICKLEN;
        game.Tick();
        if (APP_IS_PRACTISE) {
        } else {
          --game.playerCurTime;
        }
      }
      APP_GAMETIME_REMAINDER = v1;
      if (v1 < v3) {
        game.Draw();
        if (APP_IS_PRACTISE) {
        } else {
          game.DrawPlayerTime();
        }
      }
    }

    function App_UpdateGame_Demo(tickTime, realtime) {
      var v3 = APP_GAMETIME_t0;
      APP_GAMETIME_t0 = APP_t0;
      var v1 = APP_GAMETIME_t0 - v3 + APP_GAMETIME_REMAINDER;
      var v4 = v1;
      if (2000 < v1) {
        console.AddLine('resetting clock->too much lag');
        v1 = APP_GAMETIME_TICKLEN;
      }
      while (APP_GAMETIME_TICKLEN <= v1) {
        v1 -= APP_GAMETIME_TICKLEN;
        game.Tick();
        if (tickTime) {
          --game.playerCurTime;
        }
      }
      APP_GAMETIME_REMAINDER = v1;
      if (v1 < v4) {
        game.Draw();
      }
    }

    function App_ResetGameTime() {
      APP_GAMETIME_t0 = APP_t0;
      APP_GAMETIME_REMAINDER = 0;
      APP_PREV_MS = 0;
    }

    function App_PauseGame() {
      gui.Display(GUI_PAUSE);
      SetActiveProcess(App_Tick_InGamePause);
    }

    function App_Tick_InGamePause() {
      if (APP_KEY_TRIG && Key.isDown(32) || APP_KEY_TRIG && Key.isDown(APP_KEYDEF_PAUSE)) {
        APP_KEY_TRIG = false;
        App_UnpauseGame();
      } else {
        if (APP_KEY_TRIG && Key.isDown(81)) {
          if (game.isTimeTrial) {
            APP_KEY_TRIG = false;
            userdata.Save();
            GUIEvent_MainMenu_TimeTrial(true);
          } else {
            if (game.isCustom) {
              APP_KEY_TRIG = false;
              var v1 = new Sound();
              v1.stop();
              userdata.Save();
              GUIEvent_MainMenu_Custom(false);
            } else {
              APP_KEY_TRIG = false;
              gui.HideInGame();
              userdata.Save();
              App_LoadMainMenu();
            }
          }
        } else {
          APP_KEY_TRIG = false;
        }
      }
    }

    function App_StartPostLevelPause(POSTLEV_STATE) {
      if (POSTLEV_STATE == APP_POSTLEVEL_NEXTLEV) {
        gui.Display(GUI_POSTLEVEL);
        App_PostLevelResponse = App_PostLevelResponse_NextLevel;
      } else {
        if (POSTLEV_STATE == APP_POSTLEVEL_NEXTEP) {
          gui.Display(GUI_POSTLEVEL);
          App_PostLevelResponse = App_PostLevelResponse_NextEpisode;
        }
      }
      App_ResetGameTime();
      if (game.isCustom) {
        APP_CUSTOM_REPLAY_RAWDATA = game.DumpDemoData(false);
      }
      SetActiveProcess(App_Tick_PostLevelPause);
    }

    function App_Tick_PostLevelPause() {
      if (Key.isDown(32)) {
        userdata.Save();
        App_PostLevelResponse();
      } else {
        if (Key.isDown(82)) {
          APP_REPLAY_DATA = game.DumpDemoData(false);
          App_Start_PostLevelPause_Demo();
        } else {
          App_UpdateGame_Demo(false, false);
          if (!APP_IS_PRACTISE) {
            gui.DrawPlayerTime(APP_HACKY_REAL_TIME, game.playerMaxTime);
          }
        }
      }
    }

    function App_Start_PostLevelPause_Demo() {
      var v1 = new Sound();
      v1.stop();
      App_PlayerDeathEvent = App_PlayerDeathEvent_Demo;
      App_LevelPassedEvent = App_LevelPassedEvent_Demo;
      App_ResetGameTime();
      game.SetDemoFormat(false);
      game.InitRetryLevel();
      game.StopDemoPlayback();
      game.LoadDemo(APP_REPLAY_DATA);
      game.StartDemoPlayback();
      App_ResetObjects(App_Tick_PostLevelPause_Demo);
      gui.Display(GUI_POSTLEVDEMO);
      APP_DEMO_DELAY_COUNTER = 0;
    }

    function App_Tick_PostLevelPause_Demo() {
      if (Key.isDown(32)) {
        APP_KEY_TRIG = false;
        var v1 = new Sound();
        v1.stop();
        userdata.Save();
        App_PostLevelResponse();
      } else {
        if (game.GetDemoTickCount() - game.GetTime() < -130) {
          var v1 = new Sound();
          v1.stop();
          App_Start_PostLevelPause_Demo();
        } else {
          if (APP_DEMO_DELAY_AMT < APP_DEMO_DELAY_COUNTER) {
            App_UpdateGame_Demo(false, false);
          } else {
            ++APP_DEMO_DELAY_COUNTER;
            App_ResetGameTime();
          }
        }
      }
    }

    function App_StartRetryMenu(suicide) {
      if (suicide) {
        gui.Display(GUI_RETRYLEVEL_SUICIDE);
      } else {
        gui.Display(GUI_RETRYLEVEL);
      }
      APP_WAITING_TO_RETRY = true;
    }

    function App_StartGameOver() {
      gui.Display(GUI_DEFEAT);
      gui.DisplayTextBar(GUI_GAMEOVER);
      SetActiveProcess(App_Tick_GameOver);
    }

    function App_Tick_GameOver() {
      if (Key.isDown(32)) {
        userdata.Save();
        App_LoadMainMenu();
      } else {
        App_UpdateGame_Demo(false, false);
      }
    }

    function App_StartInGameDemo() {
      App_PlayerDeathEvent = App_PlayerDeathEvent_Demo;
      App_LevelPassedEvent = App_LevelPassedEvent_Demo;
      App_ResetGameTime();
      APP_DEBUG_DEATH = true;
      game.SetDemoFormat(false);
      game.InitRetryLevel();
      game.StopDemoPlayback();
      game.LoadDemo(APP_REPLAY_DATA);
      game.StartDemoPlayback();
      App_ResetObjects(App_TickInGameDemo);
      gui.Display(GUI_INGAMEDEMO);
      APP_DEMO_DELAY_COUNTER = 0;
    }

    function App_TickInGameDemo() {
      if (Key.isDown(32)) {
        APP_KEY_TRIG = false;
        var v1 = new Sound();
        v1.stop();
        App_ResetObjects(App_StartPreLevelPause);
      } else {
        if (game.GetDemoTickCount() - game.GetTime() < -130) {
          var v1 = new Sound();
          v1.stop();
          App_StartInGameDemo();
        } else {
          if (APP_DEMO_DELAY_AMT < APP_DEMO_DELAY_COUNTER) {
            App_UpdateGame_Demo(false, false);
          } else {
            ++APP_DEMO_DELAY_COUNTER;
            App_ResetGameTime();
          }
        }
      }
    }

    APP_REPLAY_DATA = '';
    APP_VICTORY = false;
    APP_DEMO_DELAY_AMT = 20;
    APP_DEMO_DELAY_COUNTER = 0;
    APP_POSTLEVEL_NEXTLEV = 1;
    APP_POSTLEVEL_NEXTEP = 2;
    APP_POSTLEVEL_TIMETRIAL = 3;
    App_PostLevelResponse = App_PostLevelResponse_NextLevel;
    APP_EPLEV_STARTTIME = 0;
    APP_PERSBEST_ACTIVE = false;
    APP_PERSBEST_PENDINGLEVNUM = 0;
    APP_PERSBEST_LEV = null;
    APP_PERSBEST_EP = null;
    APP_PERSBEST_EPDEMOS = new Array();
    APP_PERSBEST_EPDEMOS[0] = '';
    APP_PERSBEST_EPDEMOS[1] = '';
    APP_PERSBEST_EPDEMOS[2] = '';
    APP_PERSBEST_EPDEMOS[3] = '';
    APP_PERSBEST_EPDEMOS[4] = '';
    APP_PERSBEST_EPISBEST = false;
    APP_PERSBEST_EP_TIME = 0;
    APP_PERSBEST_EP_NUM = 0;
    APP_PERSBEST_EP_PENDING = false;
    APP_ONLINE_ACTIVE = false;
    APP_ONLINEGOAL_VALID = false;
    APP_ONLINEGOAL_EPISODE = 0;
    APP_ONLINEGOAL_LEVEL = 0;
    APP_ONLINEGOAL_LEVLIST = new Array();
    APP_ONLINEGOAL_LEVLIST[0] = 0;
    APP_ONLINEGOAL_LEVLIST[1] = 0;
    APP_ONLINEGOAL_LEVLIST[2] = 0;
    APP_ONLINEGOAL_LEVLIST[3] = 0;
    APP_ONLINEGOAL_LEVLIST[4] = 0;
    APP_HACKY_REAL_TIME = 0;
    APP_BEAT_TIME = 0;
    APP_IS_CHEATER = false;
    APP_DEBUG_DEATH = false;
    APP_IS_PRACTISE = false;
    APP_GAME_WAS_PLAYED = false;
    APP_GAMETIME_t0 = 0;
    APP_GAMETIME_REMAINDER = 0;
    APP_PREV_MS = 0;
  }

  frame 1 {
    function App_LevelPassedEvent_Custom() {
      console.AddLine('level completed.');
      objects.IdleObjectsAfterDeath();
      var v2 = game.GetPlayerTime();
      var v4 = game.DumpDemoData(false);
      APP_CUSTOM_REPLAY_RAWDATA = v4;
      APP_CUSTOM_REPLAY = '$' + APP_CUSTOM_LEVELNAME + '#' + APP_CUSTOM_AUTHORNAME + '#' + APP_CUSTOM_DESC + '#' + APP_CUSTOM_LEVELDATA + '#' + APP_CUSTOM_REPLAY_RAWDATA + '#';
      App_ResetGameTime();
      APP_HACKY_REAL_TIME = v2;
      var v3 = false;
      var v1 = APP_CUSTOM_RECORDS[APP_CUSTOM_SELECTEDRECORD];
      if (v1.pbest == null || v1.pbest.score < v2) {
        userdata.SetPersBest_Custom(APP_CUSTOM_LEVELDATA, v2, v4);
        App_Custom_RefreshRecordPBest(v1);
        App_Custom_RefreshButtonPBest(v1, APP_CUSTOM_SELECTEDBUTTON);
        v3 = true;
      }
      App_StartFinishedCustom(v3);
    }

    function App_StartFinishedCustom(showPB) {
      var v2 = _root._url;
      if (v2.substr(0, 4) != 'file') {
        getURL('http://www.harveycartel.org/metanet/', _top);
      }
      gui.HideAll();
      gui.DisplayTextBar(GUI_POSTLEVELCUSTOM);
      if (showPB) {
        gui.TextBarNotify(0, '             [new personal best]');
      }
      SetActiveProcess(App_TickFinishedCustom);
    }

    function App_TickFinishedCustom() {
      if (APP_KEY_TRIG && Key.isDown(32)) {
        APP_KEY_TRIG = false;
        gui.HideInGame();
        App_ResetObjects(App_StartPreLevelPause);
      } else {
        if (APP_KEY_TRIG && Key.isDown(81)) {
          APP_KEY_TRIG = false;
          gui.HideInGame();
          userdata.Save();
          GUIEvent_MainMenu_Custom(false);
        } else {
          App_UpdateGame_Demo(false, false);
          gui.DrawPlayerTime(APP_HACKY_REAL_TIME, game.playerMaxTime);
        }
      }
    }

    function App_StartNewGame_Custom(levname, authname, levdata, desc) {
      console.Show();
      APP_GAME_WAS_PLAYED = true;
      var v1 = new Sound();
      v1.stop();
      game.InitNewGame(2);
      App_PlayerDeathEvent = App_PlayerDeathEvent_Normal;
      App_LevelPassedEvent = App_LevelPassedEvent_Custom;
      App_PlayGame = App_PlayGame_Custom;
      APP_KEYDEF_PAUSE = userdata.GetPauseKey();
      APP_KEYDEF_KILL = userdata.GetKillKey();
      APP_CUSTOM_LEVELNAME = levname;
      APP_CUSTOM_AUTHORNAME = authname;
      APP_CUSTOM_DESC = desc;
      APP_CUSTOM_LEVELDATA = levdata;
      gui.Display(GUI_LOADINGLEVEL);
      App_LoadLevel_Raw(levdata, App_StartPreLevelPause);
    }

    function App_PlayGame_Custom() {
      gui.HideAll();
      gui.HideNotify();
      game.SetDemoFormat(false);
      game.StopDemoPlayback();
      game.StopRecordingDemo();
      game.InitRetryLevel();
      game.StartRecordingDemo();
      App_ResetGameTime();
      APP_VOLUNTARY_SUICIDE = false;
      APP_DEBUG_DEATH = false;
      App_PlayerDeathEvent = App_PlayerDeathEvent_Normal;
      App_LevelPassedEvent = App_LevelPassedEvent_Custom;
      SetActiveProcess(App_Tick_RunningGame);
    }

    APP_CUSTOM_REPLAY_RAWDATA = '';
    APP_CUSTOM_REPLAY = '';
    APP_CUSTOM_LEVELNAME = '';
    APP_CUSTOM_LEVELDATA = '';
    APP_CUSTOM_AUTHORNAME = '';
    APP_CUSTOM_DESC = '';
  }

  frame 1 {
    function App_StartNewGame_Debug() {
      game.InitNewGame();
      APP_DEBUG_DEATH = true;
      App_LoadDebugMenu();
    }

    function App_LoadDebugMenu() {
      _root.editor = new NinjaEditor();
      editor.Init();
      App_StartDebugMenu();
    }

    function App_KillDebugMenu() {
      editor.Destroy();
    }

    function App_StartDebugMenu() {
      App_PlayerDeathEvent = App_PlayerDeathEvent_Debug;
      App_LevelPassedEvent = App_LevelPassedEvent_Debug;
      gui.Display(GUI_DEBUGMENU);
      console.Show();
      gui.ShowTxt();
      gui.SetTxt(TXTBOX_TOP, game.DumpLevelData());
      gui.SetTxt(TXTBOX_BOTTOM, game.DumpDemoData(false));
      APP_DEBUG_MODE_ACTIVE = true;
      APP_DEBUG_DEATH = true;
      SetActiveProcess(App_Tick_DebugMenu);
    }

    function App_Tick_DebugMenu() {
      if (APP_KEY_TRIG && Key.isDown(49)) {
        APP_KEY_TRIG = false;
        game.StopRecordingDemo();
        game.InitNewGame();
        game.StartRecordingDemo();
      } else {
        if (APP_KEY_TRIG && Key.isDown(50)) {
          APP_KEY_TRIG = false;
          game.StopRecordingDemo();
        } else {
          if (APP_KEY_TRIG && Key.isDown(87)) {
            APP_KEY_TRIG = false;
            game.StopDemoPlayback();
          } else {
            if (APP_KEY_TRIG && Key.isDown(81)) {
              APP_KEY_TRIG = false;
              game.InitNewGame();
              App_ResetObjects(App_StartDemoPlayback_Debug);
            } else {
              if (APP_KEY_TRIG && Key.isDown(51)) {
                APP_KEY_TRIG = false;
                var v1 = gui.GetTxt(TXTBOX_BOTTOM);
                game.LoadDemo(v1);
              } else {
                if (APP_KEY_TRIG && Key.isDown(52)) {
                  APP_KEY_TRIG = false;
                  var v1 = game.DumpDemoData(false);
                  System.setClipboard(v1);
                  gui.ShowTxt();
                  gui.SetTxt(TXTBOX_BOTTOM, v1);
                }
              }
            }
          }
        }
      }
      if (APP_KEY_TRIG && Key.isDown(77)) {
        APP_KEY_TRIG = false;
        gui.HideTxt();
        App_KillDebugMenu();
        App_LoadMainMenu();
      } else {
        if (APP_KEY_TRIG && Key.isDown(74)) {
          APP_KEY_TRIG = false;
          App_LoadLevel_Raw(gamedata.GetBlankMap(), App_StartDebugMenu);
        } else {
          if (APP_KEY_TRIG && Key.isDown(72)) {
            APP_KEY_TRIG = false;
            App_LoadLevel_Raw(gamedata.GetFullMap(), App_StartDebugMenu);
          } else {
            if (APP_KEY_TRIG && Key.isDown(80)) {
              APP_KEY_TRIG = false;
              gui.HideTxt();
              console.Hide();
              App_PlayGame_Debug();
            } else {
              if (APP_KEY_TRIG && Key.isDown(69)) {
                APP_KEY_TRIG = false;
                gui.HideTxt();
                console.Hide();
                App_StartEditor();
              } else {
                if (APP_KEY_TRIG && Key.isDown(82)) {
                  APP_KEY_TRIG = false;
                  App_ResetObjects(App_StartDebugMenu);
                } else {
                  if (APP_KEY_TRIG && Key.isDown(84)) {
                    APP_KEY_TRIG = false;
                    gui.HideTxt();
                    console.Hide();
                    App_ResetObjects(App_StartEditor);
                  } else {
                    if (APP_KEY_TRIG && Key.isDown(76)) {
                      APP_KEY_TRIG = false;
                      v1 = gui.GetTxt(TXTBOX_TOP);
                      App_LoadLevel_Raw(v1, App_StartDebugMenu);
                    } else {
                      if (APP_KEY_TRIG && Key.isDown(83)) {
                        APP_KEY_TRIG = false;
                        v1 = game.DumpLevelData();
                        System.setClipboard(v1);
                        gui.ShowTxt();
                        gui.SetTxt(TXTBOX_TOP, v1);
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }

    function App_StartDemoPlayback_Debug() {
      game.InitNewGame();
      game.StartDemoPlayback();
      App_StartDebugMenu();
    }

    function App_PlayGame_Debug() {
      gui.HideAll();
      App_ResetGameTime();
      SetActiveProcess(App_Tick_RunningGame_Debug);
    }

    function App_Tick_RunningGame_Debug() {
      if (Key.isDown(192) || Key.isDown(220)) {
        APP_KEY_TRIG = false;
        App_StartDebugMenu();
        return undefined;
      }
      if (Key.isToggled(20)) {
        if (!APP_DID_TICK_DEBUG) {
          App_ResetGameTime();
        }
        DebugUpdateGameCode();
        App_UpdateGame();
        APP_DID_TICK_DEBUG = true;
      } else {
        if (input.MousePressed()) {
          static_rend.Clear();
          if (Key.isDown(8)) {
            player.raggy.Activate();
            player.raggy.MimicMC(0, 0, player.mc, player.facingDir, player.prevframe);
            player.mc._visible = false;
            player.raggy.Draw();
          }
          if (Key.isDown(45)) {
            player.raggy.Deactivate();
            player.mc._visible = true;
          }
          App_ResetGameTime();
          APP_GAMETIME_REMAINDER = APP_GAMETIME_TICKLEN + 1;
          DebugUpdateGameCode();
          App_UpdateGame();
          APP_DID_TICK_DEBUG = true;
        } else {
          APP_DID_TICK_DEBUG = false;
        }
      }
    }

    function App_StartEditor() {
      gui.Display(GUI_TEMP_EDITOR);
      SetActiveProcess(App_TickEditor);
      editor.Start();
    }

    function App_TickEditor() {
      App_UpdateEditor();
    }

    function App_UpdateEditor() {
      debug_rend.Clear();
      static_rend.Clear();
      editor.Tick();
    }

    APP_DEBUG_MODE_ACTIVE = true;
    APP_DID_TICK_DEBUG = false;
  }

  frame 1 {
    function App_LoadHelpDemo(demoID) {
      gamedata.SetCurrentHelpDemo(demoID);
      var v1 = gamedata.GetHelpDemoObjects();
      if (v1 != null) {
        App_BeginLoadHelpDemo(v1);
      } else {}
    }

    function App_BeginLoadHelpDemo(objStr) {
      console.AddLine('Loading Objects');
      console.AddLine('.');
      game.InitLoadObjects(objStr);
    }

    function App_LoadingHelpDemo() {
      if (!AppLoadingObjects()) {
        return false;
      }
      return true;
    }

    function App_ResetHelpDemo() {
      console.AddLine('Resetting Objects');
      console.AddLine('.');
      game.InitReloadObjects();
    }

    function App_ResettingHelpDemo() {
      if (!AppLoadingObjects()) {
        return false;
      }
      return true;
    }

    function App_LoadMenuDemo(demoID) {
      var v1 = gamedata.GetMenuDemoData(demoID);
      game.LoadDemo(v1);
      var v2 = gamedata.GetMenuDemoLevel(demoID);
      if (v2 != null) {
        App_BeginLoadMenuDemo(v2, v1);
        return true;
      } else {
        return false;
      }
    }

    function App_BeginLoadMenuDemo(levStr, demStr) {
      console.AddLine('Loading Level:');
      console.StartTab();
      console.AddLine('Loading Map');
      console.AddLine('.');
      APP_DONE_LOADING_MAP = false;
      game.InitLoadLevel(levStr);
    }

    function App_LoadingMenuDemo() {
      if (!APP_DONE_LOADING_MAP) {
        if (!AppLoadingMap()) {
          console.AddLine('Loading Objects');
          console.AddLine('.');
          APP_DONE_LOADING_MAP = true;
        }
        return true;
      }
      if (!AppLoadingObjects()) {
        console.StopTab();
        return false;
      }
      return true;
    }

    function App_LoadLevel(levelID, callback) {
      var v1 = gamedata.GetLevelData(levelID);
      if (v1 != null) {
        App_BeginLoadLevel(v1, callback);
      } else {}
    }

    function App_LoadLevel_Raw(str, callback) {
      gui.Display(GUI_LOADINGLEVEL);
      var v1 = '';
      if (str.substr(0, 1) == '$') {
        var v2 = str.split('#');
        v1 = v2[3];
      } else {
        v1 = str;
      }
      App_BeginLoadLevel(v1, callback);
    }

    function App_ResetObjects(callback) {
      gui.Display(GUI_RESETTINGLEVEL);
      App_BeginResetObjects(callback);
    }

    function App_BeginLoadLevel(levStr, callback) {
      LEVEL_LOADED_CALLBACK = callback;
      console.AddLine('Loading Level:');
      console.StartTab();
      console.AddLine('Loading Map');
      console.AddLine('.');
      APP_DONE_LOADING_MAP = false;
      game.InitLoadLevel(levStr);
      SetActiveProcess(AppLoadingLevel);
    }

    function App_BeginResetObjects(callback) {
      OBJECTS_LOADED_CALLBACK = callback;
      console.AddLine('Resetting Objects');
      console.AddLine('.');
      game.InitReloadObjects();
      SetActiveProcess(AppResettingObjects);
    }

    function AppResettingObjects() {
      if (!AppLoadingObjects()) {
        OBJECTS_LOADED_CALLBACK();
      }
    }

    function AppLoadingLevel() {
      if (!APP_DONE_LOADING_MAP) {
        if (!AppLoadingMap()) {
          console.AddLine('Loading Objects');
          console.AddLine('.');
          APP_DONE_LOADING_MAP = true;
        }
      } else {
        if (!AppLoadingObjects()) {
          console.StopTab();
          LEVEL_LOADED_CALLBACK();
        }
      }
    }

    function AppLoadingMap() {
      var v1 = 18;
      while (v1--) {
        console.Append('.');
        if (!game.LoadingMap()) {
          return false;
        }
      }
      console.Update();
      return true;
    }

    function AppLoadingObjects() {
      var v1 = 2;
      while (v1--) {
        console.Append('.');
        if (!game.LoadingObjects()) {
          return false;
        }
      }
      console.Update();
      return true;
    }

    LEVEL_LOADED_CALLBACK = null;
    OBJECTS_LOADED_CALLBACK = null;
    DEMO_LOADED_CALLBACK = null;
  }

  frame 1 {
    function InitApp() {
      gfx = new NinjaGraphicsSystem();
      particles = new ParticleManager(gfx.bufferList[LAYER_PARTICLES_FRONT], gfx.bufferList[LAYER_PARTICLES_BACK]);
      mcRend = new VectorRenderer();
      mcBuffer = mcRend.buffer;
      input = new InputManager();
      GRAV = 0.15;
      DRAG = 0.999999;
      BOUNCE = 0.7;
      FRICTION_THRESHOLD = 0.5;
      FRICTION_STATIC = 0.3;
      FRICTION_DYNAMIC_RATIO = 0.5;
      AppBuildModules();
      StartApp();
    }

  }

  frame 1 {
    fscommand('allowscale', 'false');
    fscommand('showmenu', 'false');
    APP_GAMETIME_BASETICKLEN = 25;
    APP_GAMETIME_TICKLEN = 25;
    APP_GAMETIME_SMOOTHAMT = 0;
    APP_TILE_SCALE = 12;
    APP_NUM_GRIDCOLS = 31;
    APP_NUM_GRIDROWS = 23;
    InitApp();
  }
}

