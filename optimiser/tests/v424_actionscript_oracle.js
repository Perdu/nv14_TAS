/* Extracted unchanged ActionScript function bodies. JavaScript tests ordinary
 * binary64/control flow only; graphics, ragdolls and app bookkeeping are stubs.
 * This is not an AVM1 runtime, null-method or for-in enumeration oracle.
 */
function TileMapCell() { this.next = null; }
function TileMap() {}
function ObjectManager() { this.InitDataStructs(); }
function ExitObject() {}
function GoldObject() {}
function MineObject() {}
function LaunchPadObject() {}
function PlayerObject() {}
function NinjaGame() {}
function DroneObject() {}
const noop = function () {};
const sprite = () => ({gotoAndPlay: noop, gotoAndStop: noop});
const particles = {SpawnExplosion: noop, SpawnBloodSpurt: noop, SpawnZap: noop};
const static_rend = {SetStyle: noop, DrawLine_S: noop};
const _global = {goldSnd: sprite()};
const userdata = {IncrementKillCount: noop};
const APP_DEBUG_DEATH = true, OBJTYPE_PLAYER = 5;
const KILLTYPE_ELECTRIC = 0, KILLTYPE_EXPLOSIVE = 1,
      KILLTYPE_FALL = 4, KILLTYPE_LASER = 5;
const PSTATE_FALLING = 4, PSTATE_RAGDOLL = 6, PSTATE_CELEBRATING = 7;
const NormToRot = noop;
console.AddLine = noop;
let tiles, objects, player, game;
// AS_SOURCE_SHA256 d973c7c4f9a1297e5705fd8807687b6abcc4cd621bba5e38b5743dd685698bdb
// AS_MANIFEST {"App_LevelPassedEvent_Demo": {"line": 23192, "sha256_lf": "0e1e1f5a473b2359f8e2356fd0f874f28db49763ea1329bbd689f4eb22f44d1a"}, "App_PlayerDeathEvent_Demo": {"line": 23048, "sha256_lf": "db4e40bea24bad1d6a258b8a775e911818f9513848e74cf7e2c90f4ba2360dfa"}, "DroneObject.prototype.TestVsPlayer_Zap": {"line": 9530, "sha256_lf": "0a8adb228c82ecec9a7856f1565e7dd6f791f18f299d0ce70d577c7cc9ce842a"}, "ExitObject.prototype.IdleAfterDeath": {"line": 7175, "sha256_lf": "024a844a09bb0a5b1889703e23e75055fb669f8dd77365370b03430db1a57266"}, "ExitObject.prototype.PlayerHitExit": {"line": 7202, "sha256_lf": "698ecb374ebc4919f69239cca42abba6a3d6f9162759782fd819eaa3e517fceb"}, "ExitObject.prototype.PlayerHitTrigger": {"line": 7207, "sha256_lf": "0f029c63b62d14fb815520540009da3dd12d161f7f47ce4f2fc0beb5b1c2acb1"}, "ExitObject.prototype.TestVsPlayer_Exit": {"line": 7180, "sha256_lf": "c7f6771484e3a5da75a5a390deb0f76973a66a73505e888083d59d90c2a9a5ff"}, "ExitObject.prototype.TestVsPlayer_Trigger": {"line": 7191, "sha256_lf": "5345d24abde30782b1a18dc51b10b5d38b6aa8155655b0dc2ccab05338ecd6f5"}, "GoldObject.prototype.Dissapear": {"line": 7279, "sha256_lf": "76fd18cc5fd49cda3a93096f71b04765ef5f4c10a4522602461df33469a761d3"}, "GoldObject.prototype.IdleAfterDeath": {"line": 7264, "sha256_lf": "2ebea64d4646a57c208d4c611d126af3baf8985f18cf088f974e10365f33bb86"}, "GoldObject.prototype.TestVsPlayer": {"line": 7270, "sha256_lf": "fb0a88a7d0677183c79ea3fef37c470b957a568d0afa15bd9729b72384cbe409"}, "LaunchPadObject.prototype.IdleAfterDeath": {"line": 7552, "sha256_lf": "5424ad359c6e52f581e476d854d28e67726d85991f22ae8af51dd62bc4e3f1f4"}, "LaunchPadObject.prototype.TestVsPlayer": {"line": 7554, "sha256_lf": "604dfedc96eec4db2c2440a291811ae2e211af833f4df332b2e531cb08f59da1"}, "MineObject.prototype.Explode": {"line": 8785, "sha256_lf": "754c910e1bfe8d8dcc80d5de20d34b25ab65c1025666a43896bba3d165e998a7"}, "MineObject.prototype.IdleAfterDeath": {"line": 8762, "sha256_lf": "9291f76ad204877b0fa6ffce6aa08d38005afa010ea860e0ba1b9475258ebf8a"}, "MineObject.prototype.TestVsPlayer": {"line": 8764, "sha256_lf": "f64a7e87b3afa27c3e09d8f3b50f0f472797bf8d43657e8f4ed2264814daadcb"}, "NinjaGame.prototype.GetTime": {"line": 11629, "sha256_lf": "752367a7522e769224ec2fc53c7d8110d7a9297836b0cf11f3e07dd1e138872f"}, "NinjaGame.prototype.GiveBonusTime": {"line": 11633, "sha256_lf": "ee47982e347adef0f73022ae07a1f188b2a00f0858eba2677034bb776c2ceccf"}, "NinjaGame.prototype.KillPlayer": {"line": 11643, "sha256_lf": "ca5677e26eee731493465c3913c6000a357d6aaa514e42c7a2e2f3ae39213652"}, "ObjectManager.prototype.AddToGrid": {"line": 6808, "sha256_lf": "f2aa4f0f7750fc62f2a95242eed76b72658adf9fe6814c6fa053ba58a8389971"}, "ObjectManager.prototype.GetObjType": {"line": 6844, "sha256_lf": "55017791b3428aeb07f7cf341be04c5f02bfde30ccf8b0ad2250645801061b75"}, "ObjectManager.prototype.IdleObjectsAfterDeath": {"line": 6848, "sha256_lf": "aa6ac53237295ebd3f081d863748b1dfc424fa093080789d3157626ff5278e34"}, "ObjectManager.prototype.InitDataStructs": {"line": 6783, "sha256_lf": "c5ccec2bc9c75737d602beab537ba3003bfc3bb359e0f0f02137df6e251c9871"}, "ObjectManager.prototype.Moved": {"line": 6823, "sha256_lf": "bb96f48163b2972c2025e8410f846edd54f0dff00d2c2fd1b58bbefab9c73209"}, "ObjectManager.prototype.Register": {"line": 6801, "sha256_lf": "2febf95ec10f7da46e210ea0e199548deaf4c50e4f1a14ee4db3b2489980267c"}, "ObjectManager.prototype.RemoveFromGrid": {"line": 6815, "sha256_lf": "6519dcfa9d4ea87847c0a5ca9cd657c63d4fdb54c103dc79b5b7b06a25a5756e"}, "PlayerObject.prototype.Celebrate": {"line": 11353, "sha256_lf": "7086c330f3c30ec3ac818e5a9184ca13d7021e9bfc6dc7990eda1aaa7d877453"}, "PlayerObject.prototype.CollideVsObjects": {"line": 9935, "sha256_lf": "d16cb3dfc1d5f3b8b07f8ed408dc5431f4e5b2e7cec066166b01d0656f53f266"}, "PlayerObject.prototype.Die": {"line": 11211, "sha256_lf": "ecf7e8ab257d9eb4d76b61a103065eb20456729ea61197dd8d6b81dd65d6d0e6"}, "PlayerObject.prototype.ExitCelebrate": {"line": 11361, "sha256_lf": "1821f9de98e82d9bc2702307f415a5c345f7857ce2ffad4771714a89dd80c33a"}, "PlayerObject.prototype.ExitDie": {"line": 11340, "sha256_lf": "941bf06e8678614dbbdf302a36e266f9048e1b3eaa67638661efff593bd7720f"}, "PlayerObject.prototype.ExitFall": {"line": 11148, "sha256_lf": "574964b2836726600219d08f6cc349ab1e11b138c1e06a030b1709ad062d956a"}, "PlayerObject.prototype.Fall": {"line": 11141, "sha256_lf": "248d9fa321e3f8f61366bb86d5d68ae6da8be426285f572e7aee2339abe028d8"}, "PlayerObject.prototype.IdleAfterDeath": {"line": 10095, "sha256_lf": "1ea4b8c32c4bd6e46ccd685bb5badce239f826b0613f65bd061bfb569eac4658"}, "PlayerObject.prototype.Launch": {"line": 11203, "sha256_lf": "083df315e42dd0ed3e90f8c1ad1472fec444b701d4d6e7e30f75f3c2958d121e"}, "PlayerObject.prototype.PrepareToCollide": {"line": 9926, "sha256_lf": "8ac3543f5112d61b0e191dc409e74750a9d3ccefb23bdaf585cc5566ca896dfd"}, "TileMap.prototype.GetTile_V": {"line": 3110, "sha256_lf": "6b04d96c2b730000eafb0f22bc119fdde8e087bed75bf24e928dc1e65dc7542f"}, "TileMapCell.prototype.InsertObj": {"line": 3924, "sha256_lf": "bcc40f87ad0d850a5311e03d44d866494e900e4706ceea14dfd251fabcfd00be"}, "TileMapCell.prototype.RemoveObj": {"line": 3935, "sha256_lf": "fe1bf257e7ad2d498115e84c17c0b26ed7e834150d8e021572e64a644e909d66"}}
// BEGIN AS TileMapCell.prototype.InsertObj
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
// END AS TileMapCell.prototype.InsertObj

// BEGIN AS TileMapCell.prototype.RemoveObj
TileMapCell.prototype.RemoveObj = function (obj) {
      obj.prev.next = obj.next;
      if (obj.next != null) {
        obj.next.prev = obj.prev;
      }
      obj.next = null;
      obj.prev = null;
      --this.objcounter;
    };
// END AS TileMapCell.prototype.RemoveObj

// BEGIN AS TileMap.prototype.GetTile_V
TileMap.prototype.GetTile_V = function (p) {
      return this.grid[Math.floor(p.x / this.tw)][Math.floor(p.y / this.th)];
    };
// END AS TileMap.prototype.GetTile_V

// BEGIN AS ObjectManager.prototype.InitDataStructs
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
// END AS ObjectManager.prototype.InitDataStructs

// BEGIN AS ObjectManager.prototype.Register
ObjectManager.prototype.Register = function (obj) {
      obj.UID = this.nextID++;
      this.objList[obj.UID] = obj;
      this.objArray.push(obj);
      ++this.numObjs;
    };
// END AS ObjectManager.prototype.Register

// BEGIN AS ObjectManager.prototype.AddToGrid
ObjectManager.prototype.AddToGrid = function (obj) {
      obj.cell = tiles.GetTile_V(obj.pos);
      obj.cell.InsertObj(obj);
      this.gridList[obj.UID] = obj;
      ++this.gridNum;
    };
// END AS ObjectManager.prototype.AddToGrid

// BEGIN AS ObjectManager.prototype.RemoveFromGrid
ObjectManager.prototype.RemoveFromGrid = function (obj) {
      if (this.gridList[obj.UID] != null) {
        obj.cell.RemoveObj(obj);
        delete this.gridList[obj.UID];
        --this.gridNum;
      } else {}
    };
// END AS ObjectManager.prototype.RemoveFromGrid

// BEGIN AS ObjectManager.prototype.Moved
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
// END AS ObjectManager.prototype.Moved

// BEGIN AS ObjectManager.prototype.IdleObjectsAfterDeath
ObjectManager.prototype.IdleObjectsAfterDeath = function () {
      for (var v2 in this.objList) {
        this.objList[v2].IdleAfterDeath();
      }
    };
// END AS ObjectManager.prototype.IdleObjectsAfterDeath

// BEGIN AS ObjectManager.prototype.GetObjType
ObjectManager.prototype.GetObjType = function (obj) {
      return obj.OBJ_TYPE;
    };
// END AS ObjectManager.prototype.GetObjType

// BEGIN AS ExitObject.prototype.IdleAfterDeath
ExitObject.prototype.IdleAfterDeath = function () {
      objects.RemoveFromGrid(this);
      objects.RemoveFromGrid(this.trigger);
    };
// END AS ExitObject.prototype.IdleAfterDeath

// BEGIN AS ExitObject.prototype.TestVsPlayer_Exit
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
// END AS ExitObject.prototype.TestVsPlayer_Exit

// BEGIN AS ExitObject.prototype.TestVsPlayer_Trigger
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
// END AS ExitObject.prototype.TestVsPlayer_Trigger

// BEGIN AS ExitObject.prototype.PlayerHitExit
ExitObject.prototype.PlayerHitExit = function () {
      player.Celebrate();
      App_LevelPassedEvent();
    };
// END AS ExitObject.prototype.PlayerHitExit

// BEGIN AS ExitObject.prototype.PlayerHitTrigger
ExitObject.prototype.PlayerHitTrigger = function () {
      this.mc.gotoAndPlay('exit_opening');
      this.isOpen = true;
      this.trigger.mc.gotoAndStop('exit_open');
      objects.RemoveFromGrid(this.trigger);
      objects.AddToGrid(this);
      objects.Moved(this);
    };
// END AS ExitObject.prototype.PlayerHitTrigger

// BEGIN AS GoldObject.prototype.IdleAfterDeath
GoldObject.prototype.IdleAfterDeath = function () {
      if (!this.isCollected) {
        objects.RemoveFromGrid(this);
      }
    };
// END AS GoldObject.prototype.IdleAfterDeath

// BEGIN AS GoldObject.prototype.TestVsPlayer
GoldObject.prototype.TestVsPlayer = function (guy) {
      var v5 = guy.pos;
      var v3 = this.pos.x - guy.pos.x;
      var v2 = this.pos.y - guy.pos.y;
      if (Math.sqrt(v3 * v3 + v2 * v2) < this.r + guy.r) {
        this.Dissapear();
      }
    };
// END AS GoldObject.prototype.TestVsPlayer

// BEGIN AS GoldObject.prototype.Dissapear
GoldObject.prototype.Dissapear = function () {
      this.isCollected = true;
      objects.RemoveFromGrid(this);
      this.mc.gotoAndPlay('COLLECTED');
      _global.goldSnd.gotoAndPlay('COLLECTED');
      game.GiveBonusTime();
    };
// END AS GoldObject.prototype.Dissapear

// BEGIN AS MineObject.prototype.IdleAfterDeath
MineObject.prototype.IdleAfterDeath = function () {};
// END AS MineObject.prototype.IdleAfterDeath

// BEGIN AS MineObject.prototype.TestVsPlayer
MineObject.prototype.TestVsPlayer = function (guy) {
      var v4 = guy.pos;
      var v3 = this.pos.x - v4.x;
      var v2 = this.pos.y - v4.y;
      if (Math.sqrt(v3 * v3 + v2 * v2) < this.r + guy.r) {
        this.Explode(-v3, -v2);
      }
    };
// END AS MineObject.prototype.TestVsPlayer

// BEGIN AS MineObject.prototype.Explode
MineObject.prototype.Explode = function (dx, dy) {
      game.KillPlayer(KILLTYPE_EXPLOSIVE, dx, dy, this.pos.x, this.pos.y, this);
      particles.SpawnExplosion(this.pos);
      objects.RemoveFromGrid(this);
      this.mc.gotoAndStop('mine_exploded');
    };
// END AS MineObject.prototype.Explode

// BEGIN AS LaunchPadObject.prototype.IdleAfterDeath
LaunchPadObject.prototype.IdleAfterDeath = function () {};
// END AS LaunchPadObject.prototype.IdleAfterDeath

// BEGIN AS LaunchPadObject.prototype.TestVsPlayer
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
// END AS LaunchPadObject.prototype.TestVsPlayer

// BEGIN AS PlayerObject.prototype.PrepareToCollide
PlayerObject.prototype.PrepareToCollide = function () {
      this.oldv.x = this.pos.x - this.oldpos.x;
      this.oldv.y = this.pos.y - this.oldpos.y;
      this.WAS_IN_AIR = this.IN_AIR;
      this.NEAR_WALL = false;
      this.IN_AIR = true;
      this.fCount = 0;
    };
// END AS PlayerObject.prototype.PrepareToCollide

// BEGIN AS PlayerObject.prototype.CollideVsObjects
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
// END AS PlayerObject.prototype.CollideVsObjects

// BEGIN AS PlayerObject.prototype.IdleAfterDeath
PlayerObject.prototype.IdleAfterDeath = function () {
      this.CollideVsObjects = null;
    };
// END AS PlayerObject.prototype.IdleAfterDeath

// BEGIN AS PlayerObject.prototype.Fall
PlayerObject.prototype.Fall = function () {
      this.ExitState();
      this.ExitState = this.ExitFall;
      this.curState = PSTATE_FALLING;
      this.Render = this.RenderInAir;
    };
// END AS PlayerObject.prototype.Fall

// BEGIN AS PlayerObject.prototype.ExitFall
PlayerObject.prototype.ExitFall = function () {};
// END AS PlayerObject.prototype.ExitFall

// BEGIN AS PlayerObject.prototype.Launch
PlayerObject.prototype.Launch = function (x, y) {
      this.oldpos.x = this.pos.x;
      this.oldpos.y = this.pos.y;
      this.pos.x += x;
      this.pos.y += y;
      this.Fall();
    };
// END AS PlayerObject.prototype.Launch

// BEGIN AS PlayerObject.prototype.Die
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
// END AS PlayerObject.prototype.Die

// BEGIN AS PlayerObject.prototype.ExitDie
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
// END AS PlayerObject.prototype.ExitDie

// BEGIN AS PlayerObject.prototype.Celebrate
PlayerObject.prototype.Celebrate = function () {
      this.ExitState();
      this.ExitState = this.ExitCelebrate;
      this.curState = PSTATE_CELEBRATING;
      this.Think = this.ThinkCelebrate;
      this.celeb_wasinair = this.IN_AIR;
    };
// END AS PlayerObject.prototype.Celebrate

// BEGIN AS PlayerObject.prototype.ExitCelebrate
PlayerObject.prototype.ExitCelebrate = function () {
      this.d = this.normDrag;
      this.Think = PlayerObject.prototype.Think;
    };
// END AS PlayerObject.prototype.ExitCelebrate

// BEGIN AS NinjaGame.prototype.GetTime
NinjaGame.prototype.GetTime = function () {
      return this.tickCounter;
    };
// END AS NinjaGame.prototype.GetTime

// BEGIN AS NinjaGame.prototype.GiveBonusTime
NinjaGame.prototype.GiveBonusTime = function () {
      this.playerCurTime += this.playerBonusTime;
    };
// END AS NinjaGame.prototype.GiveBonusTime

// BEGIN AS NinjaGame.prototype.KillPlayer
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
// END AS NinjaGame.prototype.KillPlayer

// BEGIN AS DroneObject.prototype.TestVsPlayer_Zap
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
// END AS DroneObject.prototype.TestVsPlayer_Zap

// BEGIN AS App_PlayerDeathEvent_Demo
function App_PlayerDeathEvent_Demo() {
      objects.IdleObjectsAfterDeath();
    }
// END AS App_PlayerDeathEvent_Demo

// BEGIN AS App_LevelPassedEvent_Demo
function App_LevelPassedEvent_Demo() {
      objects.IdleObjectsAfterDeath();
    }
// END AS App_LevelPassedEvent_Demo

PlayerObject.prototype.Think = noop;
const App_PlayerDeathEvent = App_PlayerDeathEvent_Demo;
let completed = false;
function App_LevelPassedEvent() {
    completed = true;
    App_LevelPassedEvent_Demo();
}
function reset() {
    completed = false;
    tiles = new TileMap(); tiles.tw = tiles.th = 24;
    tiles.grid = Array.from({length: 33}, () => Array.from({length: 25}, () => new TileMapCell()));
    for (let i = 0; i < 33; i++) for (let j = 0; j < 25; j++) {
        const c = tiles.grid[i][j];
        c.nL = tiles.grid[i-1]?.[j]; c.nR = tiles.grid[i+1]?.[j];
        c.nU = tiles.grid[i][j-1]; c.nD = tiles.grid[i][j+1];
    }
    objects = new ObjectManager(); game = new NinjaGame();
    game.tickCounter = 0; game.playerCurTime = 0; game.playerBonusTime = 80;
    player = new PlayerObject();
    Object.assign(player, {pos: {x: 60, y: 60}, oldpos: {x: 60, y: 60}, r: 10,
        d: 0.99, g: 0.15, normDrag: 0.99, IN_AIR: true, NEAR_WALL: false,
        oldv: {x: 0, y: 0}, isDead: false, curState: 0, mc: sprite(), snd: sprite(),
        ExitState: noop, TickRagdoll: noop, TickNormal: noop,
        raggy: {Activate: noop, MimicMC: noop, Shove_VertBias: noop,
                Deactivate: noop, Unexplode: noop, Explode: noop}});
    objects.Register(player);
}
function add(prototype, x, y, extra = {}) {
    const object = Object.create(prototype);
    Object.assign(object, {pos: {x, y}, r: prototype === MineObject.prototype ? 12 * 0.3333333333333333 : 6, mc: sprite(), name: 'fixture'}, extra);
    objects.Register(object); objects.AddToGrid(object);
    return object;
}
function exit(x = 60, y = 60) {
    const object = Object.create(ExitObject.prototype);
    Object.assign(object, {pos: {x, y}, r: 12, mc: sprite(), isOpen: false});
    objects.Register(object);
    object.TestVsPlayer = object.TestVsPlayer_Exit;
    object.trigger = {pos: {x: 60, y: 60}, r: 6, mc: sprite(), exit: object,
                      TestVsPlayer: object.TestVsPlayer_Trigger};
    objects.AddToGrid(object.trigger);
    return object;
}
function stepScan() {
    const oldx = player.oldpos.x, oldy = player.oldpos.y;
    player.oldpos.x = player.pos.x; player.oldpos.y = player.pos.y;
    player.pos.x += player.d * (player.oldpos.x - oldx);
    player.pos.y += player.d * (player.oldpos.y - oldy) + player.g;
    player.cell = tiles.GetTile_V(player.pos);
    player.PrepareToCollide();
    // The callback is entered while callable. IdleAfterDeath can null it during
    // this invocation, but the currently running body continues unchanged.
    player.CollideVsObjects();
    game.tickCounter++;
}
function result() {
    return {complete: completed, dead: player.isDead,
            bonus: game.playerCurTime, x: player.pos.x, y: player.pos.y};
}
const output = {};
reset(); add(GoldObject.prototype, 60, 76.3, {isCollected: false}); exit();
stepScan(); stepScan(); output.later_gold = result();
reset(); add(MineObject.prototype, 60, 60); exit();
stepScan(); stepScan(); output.same_cell_mine = result();
reset(); add(MineObject.prototype, 60, 74.3); exit();
stepScan(); stepScan(); output.later_cell_mine = result();
reset(); player.pos.y = player.oldpos.y = 70;
add(MineObject.prototype, 60, 70);
add(LaunchPadObject.prototype, 60, 72, {nx: 0, ny: -1, strength: 12 * 0.4285714285714286});
stepScan(); output.death_pad = {...result(), state: player.curState,
    normal_tick: player.Tick === player.TickNormal,
    think_restored: player.Think === PlayerObject.prototype.Think,
    objects_disabled: player.CollideVsObjects === null};
reset(); player.pos = {x: 36.05, y: 54.99993421041241};
const zap = Object.create(DroneObject.prototype);
zap.pos = {x: 36, y: 36}; zap.r = 9;
zap.TestVsPlayer_Zap(player); output.zap_tangent = result();
console.log(JSON.stringify(output));
