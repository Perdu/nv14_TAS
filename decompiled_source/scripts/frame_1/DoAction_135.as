function App_StartConfigMenu()
{
   gui.Display(GUI_CONFIGURE);
   SetActiveProcess(App_TickConfigure);
   var menuMC = gui.GetCurrentMC();
   var jbut = eval(menuMC + ".configmenu.jbut");
   var lbut = eval(menuMC + ".configmenu.lbut");
   var rbut = eval(menuMC + ".configmenu.rbut");
   var kbut = eval(menuMC + ".configmenu.kbut");
   var pbut = eval(menuMC + ".configmenu.pbut");
   var bbut = eval(menuMC + ".configmenu.bbut");
   jbut.keyname.text = App_GetKeyName(userdata.GetJumpKey());
   lbut.keyname.text = App_GetKeyName(userdata.GetLeftKey());
   rbut.keyname.text = App_GetKeyName(userdata.GetRightKey());
   kbut.keyname.text = App_GetKeyName(userdata.GetKillKey());
   pbut.keyname.text = App_GetKeyName(userdata.GetPauseKey());
   bbut.keyname.text = App_GetKeyName(userdata.GetBossKey());
   var namebox = eval(menuMC + ".configmenu.namebox");
   var passbox = eval(menuMC + ".configmenu.passbox");
   passbox.password = true;
   var emailbox = eval(menuMC + ".configmenu.emailbox");
   if(userdata.IsUserAnon())
   {
      namebox.text = "";
      passbox.text = "";
      emailbox.text = "";
   }
   else
   {
      namebox.text = userdata.GetUserName();
      passbox.text = userdata.GetUserPass();
      emailbox.text = userdata.GetUserEmail();
   }
   var colList = new Array();
   colList[0] = 0;
   colList[1] = 15466636;
   colList[2] = 8551168;
   colList[3] = 1598085;
   colList[4] = 7820163;
   colList[5] = 6693410;
   colList[6] = 16777215;
   colList[7] = 13408512;
   colList[8] = 7960968;
   colList[9] = 12895433;
   var numcol = userdata.GetNumUnlockedColors();
   var curcol = userdata.GetNinjaColor();
   var isCustCol = userdata.IsNinjaColorCustom();
   var i = 0;
   while(i < 10)
   {
      var colbut = eval(menuMC + ".configmenu.col" + i);
      if(i <= numcol)
      {
         colbut._visible = true;
         colbut.col = colList[i];
         var tempc = new Color(colbut.colpanel);
         tempc.setRGB(colList[i]);
         colbut.gfx.gotoAndStop(1);
         colbut.onRelease = function()
         {
            _root.App_Configure_ColorButtonPressed(this);
         };
         colbut.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         colbut.onRollOut = function()
         {
            this.gfx.gotoAndStop(1);
         };
         colbut.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(1);
         };
         if(!isCustCol && curcol == colList[i])
         {
            _root.App_Configure_ColorButtonPressed(colbut);
         }
      }
      else
      {
         colbut._visible = false;
      }
      i++;
   }
   var customFpanel = eval(menuMC + ".configmenu.customFpanel");
   if(userdata.GetCustomFlavourUnlocked())
   {
      customFpanel._visible = true;
      var custbut = eval(menuMC + ".configmenu.customFpanel.colbutton");
      custbut.isCustom = true;
      custbut.gfx.gotoAndStop(1);
      custbut.onRelease = function()
      {
         _root.App_Configure_CustomColorButtonPressed();
      };
      custbut.onRollOver = function()
      {
         this.gfx.gotoAndStop(2);
      };
      custbut.onRollOut = function()
      {
         this.gfx.gotoAndStop(1);
      };
      custbut.onReleaseOutside = function()
      {
         this.gfx.gotoAndStop(1);
      };
      var ccol = userdata.GetNinjaColor_Custom();
      var tempc = new Color(custbut.colpanel);
      tempc.setRGB(ccol);
      var hex = ccol;
      var chanR = hex >> 16;
      var tempH = hex ^ chanR << 16;
      var chanG = tempH >> 8;
      var chanB = tempH ^ chanG << 8;
      var sR = eval(menuMC + ".configmenu.customFpanel.slider_r.slide");
      var sG = eval(menuMC + ".configmenu.customFpanel.slider_g.slide");
      var sB = eval(menuMC + ".configmenu.customFpanel.slider_b.slide");
      sR._x = chanR - 128;
      sG._x = chanG - 128;
      sB._x = chanB - 128;
      var hexR = chanR.toString(16);
      var hexG = chanG.toString(16);
      var hexB = chanB.toString(16);
      sR.num.text = "" + hexR.toUpperCase();
      sG.num.text = "" + hexG.toUpperCase();
      sB.num.text = "" + hexB.toUpperCase();
      if(isCustCol)
      {
         App_Configure_CustomColorButtonPressed();
      }
   }
   else
   {
      customFpanel._visible = false;
   }
   var importstat = eval(menuMC + ".configmenu.importStatus");
   importstat._visible = false;
   var importbut = eval(menuMC + ".configmenu.importButton");
   importbut.gotoAndStop(1);
   importbut.onRelease = function()
   {
      _root.App_Configure_ImportButtonPressed();
   };
   importbut.onRollOver = function()
   {
      this.gotoAndStop(2);
   };
   importbut.onRollOut = function()
   {
      this.gotoAndStop(1);
   };
   importbut.onReleaseOutside = function()
   {
      this.gotoAndStop(1);
   };
   var vol = userdata.GetVol();
   var slideMC = eval(menuMC + ".configmenu.volslider.slide");
   slideMC.init = function()
   {
      var _loc3_ = _root.userdata.GetVol();
      this._x = _loc3_ / 100 * 96 - 48;
      this.num.text = "" + _loc3_;
   };
   slideMC.init();
   var speedMC = eval(menuMC + ".configmenu.speedPanel");
   var numColumns = userdata.GetNumUnlockedColors();
   if(6 <= numColumns)
   {
      if(APP_CONFIG_OVERCLOCK == null)
      {
         APP_CONFIG_OVERCLOCK = 0;
      }
      speedMC._visible = true;
      speedMC.enabled = true;
      App_SpeedSliderMoved(APP_CONFIG_OVERCLOCK,true);
   }
   else
   {
      speedMC._visible = false;
      speedMC.enabled = false;
   }
   var onBut = eval(menuMC + ".configmenu.onlineOnButton");
   var offBut = eval(menuMC + ".configmenu.onlineOffButton");
   var activeButton = null;
   var passiveButton = null;
   var toggleState = false;
   if(userdata.GetOnlineActive())
   {
      App_ChangeUser();
      toggleState = false;
      activeButton = onBut;
      passiveButton = offBut;
   }
   else
   {
      onlineclient.ClearCallback();
      var onlinestatus = eval(menuMC + ".configmenu.onlinestatus");
      onlinestatus.text = "offline";
      toggleState = true;
      activeButton = offBut;
      passiveButton = onBut;
   }
   activeButton.gotoAndStop(2);
   activeButton.onRelease = null;
   activeButton.onReleaseOutside = null;
   activeButton.onRollOut = null;
   activeButton.onRollOver = null;
   passiveButton.gotoAndStop(1);
   passiveButton.onRelease = function()
   {
      _root.App_Configure_OnlineButtonPressed(toggleState);
   };
   passiveButton.onRollOver = function()
   {
      this.gotoAndStop(2);
   };
   passiveButton.onRollOut = function()
   {
      this.gotoAndStop(1);
   };
   passiveButton.onReleaseOutside = function()
   {
      this.gotoAndStop(1);
   };
   var mqBut = eval(menuMC + ".configmenu.mqButton");
   var hqBut = eval(menuMC + ".configmenu.hqButton");
   var activeQButton = null;
   var passiveQButton = null;
   var qState = false;
   if(userdata.GetHighQuality())
   {
      qState = false;
      activeQButton = hqBut;
      passiveQButton = mqBut;
   }
   else
   {
      qState = true;
      activeQButton = mqBut;
      passiveQButton = hqBut;
   }
   activeQButton.gotoAndStop(2);
   activeQButton.onRelease = null;
   activeQButton.onRollOut = null;
   activeQButton.onRollOver = null;
   activeQButton.onReleaseOutside = null;
   passiveQButton.gotoAndStop(1);
   passiveQButton.onRelease = function()
   {
      _root.App_Configure_QualityButtonPressed(qState);
   };
   passiveQButton.onRollOver = function()
   {
      this.gotoAndStop(2);
   };
   passiveQButton.onRollOut = function()
   {
      this.gotoAndStop(1);
   };
   passiveQButton.onReleaseOutside = function()
   {
      this.gotoAndStop(1);
   };
   var pOnBut = eval(menuMC + ".configmenu.practiseOnButton");
   var pOffBut = eval(menuMC + ".configmenu.practiseOffButton");
   var activePButton = null;
   var passivePButton = null;
   var qState = false;
   if(userdata.GetPractiseMode())
   {
      qState = false;
      activePButton = pOnBut;
      passivePButton = pOffBut;
   }
   else
   {
      qState = true;
      activePButton = pOffBut;
      passivePButton = pOnBut;
   }
   activePButton.gotoAndStop(2);
   activePButton.onRelease = null;
   activePButton.onRollOut = null;
   activePButton.onRollOver = null;
   activePButton.onReleaseOutside = null;
   passivePButton.gotoAndStop(1);
   passivePButton.onRelease = function()
   {
      _root.App_Configure_PractiseButtonPressed(qState);
   };
   passivePButton.onRollOver = function()
   {
      this.gotoAndStop(2);
   };
   passivePButton.onRollOut = function()
   {
      this.gotoAndStop(1);
   };
   passivePButton.onReleaseOutside = function()
   {
      this.gotoAndStop(1);
   };
}
function App_TestForSecret0()
{
   var _loc1_;
   var _loc2_;
   if(!APP_IS_CHEATER && !APP_IS_PRACTISE)
   {
      _loc1_ = userdata.GetNumUnlockedColors();
      _loc2_ = userdata.GetNumBeaten();
      if(_loc2_ < _loc1_)
      {
         onlineclient.ClearCallback();
         userdata.SetNumBeaten(_loc1_);
         if(_loc1_ == 10)
         {
            userdata.SetCustomFlavourUnlocked(true);
            gui.TextBarNotify(3,"..CUSTOM FLAVOUR UNLOCKED!");
            gui.TextBarNotify(2,"kudos -- you\'ve completed N!!");
            gui.TextBarNotify(1,"your skills are most impressive.");
            gui.TextBarNotify(0,"(see [configure] menu for details)");
         }
         else
         {
            gui.TextBarNotify(1,"..new ninja flavour unlocked!");
            gui.TextBarNotify(0,"(see [configure] menu for details)");
            if(_loc1_ == 6)
            {
               onlineclient.ClearCallback();
               userdata.SetSecret(0,0);
               gui.TextBarNotify(3,"..OVERCLOCK MODE UNLOCKED!");
               gui.TextBarNotify(2,"kudos!!");
            }
         }
      }
   }
}
function App_TickConfigure()
{
   App_UpdateMainMenu();
}
function App_Configure_ImportButtonPressed()
{
   userdata.ImportUserData();
   App_StartConfigMenu();
   var menuMC = gui.GetCurrentMC();
   var importstat = eval(menuMC + ".configmenu.importStatus");
   importstat._visible = true;
}
function App_ColSliderMoved()
{
   var menuMC = gui.GetCurrentMC();
   var sR = eval(menuMC + ".configmenu.customFpanel.slider_r.slide");
   var sG = eval(menuMC + ".configmenu.customFpanel.slider_g.slide");
   var sB = eval(menuMC + ".configmenu.customFpanel.slider_b.slide");
   var valR = Math.min(255,Math.max(0,sR._x + 128));
   var valG = Math.min(255,Math.max(0,sG._x + 128));
   var valB = Math.min(255,Math.max(0,sB._x + 128));
   var hexR = valR.toString(16);
   var hexG = valG.toString(16);
   var hexB = valB.toString(16);
   sR.num.text = "" + hexR.toUpperCase();
   sG.num.text = "" + hexG.toUpperCase();
   sB.num.text = "" + hexB.toUpperCase();
   var hex = valR << 16 ^ valG << 8 ^ valB;
   var but = eval(menuMC + ".configmenu.customFpanel.colbutton");
   var tempc = new Color(but.colpanel);
   tempc.setRGB(hex);
}
function App_ColSliderReleased(val)
{
   App_ColSliderMoved(val);
   App_Configure_CustomColorButtonPressed();
}
function App_Configure_SetFocusCustomColorButton()
{
   if(APP_CONFIG_SELECTEDCOLBUTTON != null)
   {
      var colbut = APP_CONFIG_SELECTEDCOLBUTTON;
      colbut.gfx.gotoAndStop(1);
      colbut.onRelease = function()
      {
         _root.App_Configure_ColorButtonPressed(this);
      };
      colbut.onRollOver = function()
      {
         this.gfx.gotoAndStop(2);
      };
      colbut.onRollOut = function()
      {
         this.gfx.gotoAndStop(1);
      };
      colbut.onReleaseOutside = function()
      {
         this.gfx.gotoAndStop(1);
      };
   }
   var menuMC = gui.GetCurrentMC();
   var but = eval(menuMC + ".configmenu.customFpanel.colbutton");
   APP_CONFIG_SELECTEDCOLBUTTON = but;
   but.gfx.gotoAndStop(3);
   but.onRelease = null;
   but.onRollOver = null;
   but.onRollOut = null;
   but.onReleaseOutside = null;
}
function App_Configure_CustomColorButtonPressed()
{
   App_Configure_SetFocusCustomColorButton();
   var menuMC = gui.GetCurrentMC();
   var but = eval(menuMC + ".configmenu.customFpanel.colbutton");
   var tempc = new Color(but.colpanel);
   var hex = tempc.getRGB();
   userdata.SetNinjaColor(hex,true);
}
function App_Configure_ColorButtonPressed(but)
{
   var _loc3_;
   if(APP_CONFIG_SELECTEDCOLBUTTON != null)
   {
      _loc3_ = APP_CONFIG_SELECTEDCOLBUTTON;
      if(_loc3_.isCustom)
      {
         _loc3_.gfx.gotoAndStop(1);
         _loc3_.onRelease = function()
         {
            _root.App_Configure_CustomColorButtonPressed();
         };
         _loc3_.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         _loc3_.onRollOut = function()
         {
            this.gfx.gotoAndStop(1);
         };
         _loc3_.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(1);
         };
      }
      else
      {
         _loc3_.gfx.gotoAndStop(1);
         _loc3_.onRelease = function()
         {
            _root.App_Configure_ColorButtonPressed(this);
         };
         _loc3_.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         _loc3_.onRollOut = function()
         {
            this.gfx.gotoAndStop(1);
         };
         _loc3_.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(1);
         };
      }
   }
   APP_CONFIG_SELECTEDCOLBUTTON = but;
   but.gfx.gotoAndStop(3);
   but.onRelease = null;
   but.onRollOver = null;
   but.onRollOut = null;
   but.onReleaseOutside = null;
   userdata.SetNinjaColor(but.col,false);
}
function App_Configure_OnlineButtonPressed(toggleState)
{
   userdata.SetOnlineActive(toggleState);
   var menuMC = gui.GetCurrentMC();
   var onBut = eval(menuMC + ".configmenu.onlineOnButton");
   var offBut = eval(menuMC + ".configmenu.onlineOffButton");
   var activeButton = null;
   var passiveButton = null;
   var newState = false;
   if(toggleState)
   {
      App_ChangeUser();
      newState = false;
      activeButton = onBut;
      passiveButton = offBut;
   }
   else
   {
      onlineclient.ClearCallback();
      var onlinestatus = eval(menuMC + ".configmenu.onlinestatus");
      onlinestatus.text = "offline";
      newState = true;
      activeButton = offBut;
      passiveButton = onBut;
   }
   activeButton.gotoAndStop(2);
   activeButton.onRelease = null;
   activeButton.onReleaseOutside = null;
   activeButton.onRollOut = null;
   activeButton.onRollOver = null;
   passiveButton.gotoAndStop(1);
   passiveButton.onRelease = function()
   {
      _root.App_Configure_OnlineButtonPressed(newState);
   };
   passiveButton.onRollOver = function()
   {
      this.gotoAndStop(2);
   };
   passiveButton.onRollOut = function()
   {
      this.gotoAndStop(1);
   };
   passiveButton.onReleaseOutside = function()
   {
      this.gotoAndStop(1);
   };
}
function App_Configure_QualityButtonPressed(qState)
{
   userdata.SetHighQuality(qState);
   var menuMC = gui.GetCurrentMC();
   var mqBut = eval(menuMC + ".configmenu.mqButton");
   var hqBut = eval(menuMC + ".configmenu.hqButton");
   var activeQButton = null;
   var passiveQButton = null;
   var newState = false;
   if(qState)
   {
      _quality = "HIGH";
      newState = false;
      activeQButton = hqBut;
      passiveQButton = mqBut;
   }
   else
   {
      _quality = "MEDIUM";
      newState = true;
      activeQButton = mqBut;
      passiveQButton = hqBut;
   }
   activeQButton.gotoAndStop(2);
   activeQButton.onRelease = null;
   activeQButton.onReleaseOutside = null;
   activeQButton.onRollOut = null;
   activeQButton.onRollOver = null;
   passiveQButton.gotoAndStop(1);
   passiveQButton.onRelease = function()
   {
      _root.App_Configure_QualityButtonPressed(newState);
   };
   passiveQButton.onRollOver = function()
   {
      this.gotoAndStop(2);
   };
   passiveQButton.onRollOut = function()
   {
      this.gotoAndStop(1);
   };
   passiveQButton.onReleaseOutside = function()
   {
      this.gotoAndStop(1);
   };
}
function App_Configure_PractiseButtonPressed(qState)
{
   userdata.SetPractiseMode(qState);
   var menuMC = gui.GetCurrentMC();
   var pOnBut = eval(menuMC + ".configmenu.practiseOnButton");
   var pOffBut = eval(menuMC + ".configmenu.practiseOffButton");
   var activePButton = null;
   var passivePButton = null;
   var newState = false;
   if(qState)
   {
      newState = false;
      activePButton = pOnBut;
      passivePButton = pOffBut;
   }
   else
   {
      newState = true;
      activePButton = pOffBut;
      passivePButton = pOnBut;
   }
   activePButton.gotoAndStop(2);
   activePButton.onRelease = null;
   activePButton.onReleaseOutside = null;
   activePButton.onRollOut = null;
   activePButton.onRollOver = null;
   passivePButton.gotoAndStop(1);
   passivePButton.onRelease = function()
   {
      _root.App_Configure_PractiseButtonPressed(newState);
   };
   passivePButton.onRollOver = function()
   {
      this.gotoAndStop(2);
   };
   passivePButton.onRollOut = function()
   {
      this.gotoAndStop(1);
   };
   passivePButton.onReleaseOutside = function()
   {
      this.gotoAndStop(1);
   };
}
function App_VolumeSliderMoved(val)
{
   var vol = Math.round(val);
   var s = new Sound();
   s.setVolume(vol);
   var menuMC = gui.GetCurrentMC();
   var slideMC = eval(menuMC + ".configmenu.volslider.slide");
   slideMC.num.text = "" + vol;
}
function App_VolumeSliderReleased(val)
{
   App_VolumeSliderMoved(val);
   var _loc1_ = Math.round(val);
   userdata.SetVol(_loc1_);
}
function App_SpeedSliderMoved(val, isFinal)
{
   var numColumns = userdata.GetNumUnlockedColors();
   if(6 <= numColumns)
   {
      var overclock = Math.round(Math.max(0,Math.min(10,val * 10)));
      APP_GAMETIME_TICKLEN = APP_GAMETIME_BASETICKLEN - overclock;
      var menuMC = gui.GetCurrentMC();
      var speedMC = eval(menuMC + ".configmenu.speedPanel.speedSlider.slide");
      speedMC.num.text = "" + overclock;
      speedMC._x = overclock / 10 * 96 - 48;
      if(isFinal)
      {
         APP_CONFIG_OVERCLOCK = val;
      }
   }
}
function App_AddUser()
{
   var menuMC = gui.GetCurrentMC();
   var namebox = eval(menuMC + ".configmenu.namebox");
   var passbox = eval(menuMC + ".configmenu.passbox");
   var emailbox = eval(menuMC + ".configmenu.emailbox");
   var onlinestatus = eval(menuMC + ".configmenu.onlinestatus");
   var n = namebox.text;
   var p = passbox.text;
   var e = emailbox.text;
   if(n == "" || n == "guy_incognito")
   {
      onlinestatus.text = "logged in as anonymous.";
      userdata.SetUserAnon(true);
      namebox.text = "guy_incognito";
      passbox.text = "";
      emailbox.text = "";
   }
   else
   {
      onlinestatus.text = "waiting for server response..";
      userdata.SetUserAnon(false);
      userdata.SetUserName(n);
      userdata.SetUserPass(p);
      userdata.SetUserEmail(e);
      onlineclient.AddNewUser(n,p,e,App_NotifyUserAdded);
   }
}
function App_NotifyUserAdded(isValid)
{
   var menuMC = gui.GetCurrentMC();
   var namebox = eval(menuMC + ".configmenu.namebox");
   var passbox = eval(menuMC + ".configmenu.passbox");
   var emailbox = eval(menuMC + ".configmenu.emailbox");
   var onlinestatus = eval(menuMC + ".configmenu.onlinestatus");
   var qryData = onlineclient.GetLoadedData();
   if(isValid)
   {
      if(qryData.created == 1)
      {
         onlinestatus.text = "user created: " + qryData.name + " (login successful)";
         namebox.text = qryData.name;
         passbox.text = userdata.GetUserPass();
         emailbox.text = userdata.GetUserEmail();
         userdata.SetUserName(qryData.name);
      }
      else
      {
         var stat = qryData.stat;
         onlinestatus.text = "" + stat;
      }
   }
   else
   {
      var stat = qryData.stat;
      onlinestatus.text = "error: " + stat;
   }
}
function App_ChangeUser()
{
   var menuMC = gui.GetCurrentMC();
   var namebox = eval(menuMC + ".configmenu.namebox");
   var passbox = eval(menuMC + ".configmenu.passbox");
   var emailbox = eval(menuMC + ".configmenu.emailbox");
   var onlinestatus = eval(menuMC + ".configmenu.onlinestatus");
   var n = namebox.text;
   var p = passbox.text;
   var e = emailbox.text;
   if(n == "" || n == "guy_incognito")
   {
      onlinestatus.text = "logged in as anonymous.";
      userdata.SetUserAnon(true);
      namebox.text = "guy_incognito";
      passbox.text = "";
      emailbox.text = "";
   }
   else
   {
      onlinestatus.text = "waiting for server response..";
      userdata.SetUserAnon(false);
      userdata.SetUserName(n);
      userdata.SetUserPass(p);
      userdata.SetUserEmail(e);
      onlineclient.TestUserLogin(n,p,e,App_NotifyUserLogin);
   }
}
function App_NotifyUserLogin(isValid)
{
   var menuMC = gui.GetCurrentMC();
   var namebox = eval(menuMC + ".configmenu.namebox");
   var passbox = eval(menuMC + ".configmenu.passbox");
   var emailbox = eval(menuMC + ".configmenu.emailbox");
   var onlinestatus = eval(menuMC + ".configmenu.onlinestatus");
   var qryData = onlineclient.GetLoadedData();
   if(isValid)
   {
      if(qryData.created == 0)
      {
         onlinestatus.text = "login successful: " + qryData.name;
         namebox.text = qryData.name;
         passbox.text = userdata.GetUserPass();
         emailbox.text = userdata.GetUserEmail();
      }
      else
      {
         var stat = qryData.stat;
         onlinestatus.text = "error: " + stat;
      }
   }
   else
   {
      var stat = qryData.stat;
      onlinestatus.text = "error: " + stat;
   }
}
function App_SubmitKeyConfig(kbut, ktype, kcode)
{
   APP_KEY_TRIG = false;
   gui.HideTextMenu();
   Key.removeListener(kbut);
   if(kcode != 81)
   {
      kbut.keyname.text = App_GetKeyName(kcode);
      if(ktype == "jump")
      {
         userdata.SetJumpKey(kcode);
      }
      else if(ktype == "left")
      {
         userdata.SetLeftKey(kcode);
      }
      else if(ktype == "right")
      {
         userdata.SetRightKey(kcode);
      }
      else if(ktype == "pause")
      {
         userdata.SetPauseKey(kcode);
      }
      else if(ktype == "kill")
      {
         userdata.SetKillKey(kcode);
      }
      else if(ktype == "boss")
      {
         userdata.SetBossKey(kcode);
      }
   }
}
function App_FocusKeyConfig(kbut)
{
   gui.DisplayTextBar(GUI_KEYCONFIG);
   Key.addListener(kbut);
}
function App_ResetKeyConfig()
{
   userdata.SetJumpKey(16);
   userdata.SetLeftKey(37);
   userdata.SetRightKey(39);
   userdata.SetPauseKey(80);
   userdata.SetKillKey(75);
   userdata.SetBossKey(9);
   var menuMC = gui.GetCurrentMC();
   var jbut = eval(menuMC + ".configmenu.jbut");
   var lbut = eval(menuMC + ".configmenu.lbut");
   var rbut = eval(menuMC + ".configmenu.rbut");
   var pbut = eval(menuMC + ".configmenu.pbut");
   var kbut = eval(menuMC + ".configmenu.kbut");
   var bbut = eval(menuMC + ".configmenu.bbut");
   jbut.keyname.text = App_GetKeyName(userdata.GetJumpKey());
   lbut.keyname.text = App_GetKeyName(userdata.GetLeftKey());
   rbut.keyname.text = App_GetKeyName(userdata.GetRightKey());
   pbut.keyname.text = App_GetKeyName(userdata.GetPauseKey());
   kbut.keyname.text = App_GetKeyName(userdata.GetKillKey());
   bbut.keyname.text = App_GetKeyName(userdata.GetBossKey());
}
function App_GetKeyName(kcode)
{
   var _loc1_ = "";
   if(kcode == 37)
   {
      _loc1_ += "L arrow";
   }
   else if(kcode == 39)
   {
      _loc1_ += "R arrow";
   }
   else if(kcode == 38)
   {
      _loc1_ += "U arrow";
   }
   else if(kcode == 40)
   {
      _loc1_ += "D arrow";
   }
   else if(kcode == 32)
   {
      _loc1_ += "space";
   }
   else if(kcode == 16)
   {
      _loc1_ += "shift";
   }
   else if(kcode == 17)
   {
      _loc1_ += "ctrl";
   }
   else if(kcode == 18)
   {
      _loc1_ += "alt";
   }
   else if(kcode == 13)
   {
      _loc1_ += "enter";
   }
   else if(kcode == 9)
   {
      _loc1_ += "tab";
   }
   else
   {
      _loc1_ += String.fromCharCode(kcode);
   }
   return _loc1_;
}
APP_CONFIG_SELECTEDCOLBUTTON = null;
APP_CONFIG_OVERCLOCK = null;
