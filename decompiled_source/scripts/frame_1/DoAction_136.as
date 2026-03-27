function App_StartPlayMenu()
{
   gui.Display(GUI_PLAYMENU);
   SetActiveProcess(App_TickPlayMenu);
   var ep0 = userdata.GetEpisodeBeaten(0);
   var ep1 = userdata.GetEpisodeBeaten(1);
   var ep2 = userdata.GetEpisodeBeaten(2);
   var ep3 = userdata.GetEpisodeBeaten(3);
   var ep4 = userdata.GetEpisodeBeaten(4);
   var ep5 = userdata.GetEpisodeBeaten(5);
   var ep6 = userdata.GetEpisodeBeaten(6);
   var ep7 = userdata.GetEpisodeBeaten(7);
   var ep8 = userdata.GetEpisodeBeaten(8);
   var ep9 = userdata.GetEpisodeBeaten(9);
   var ep0r = userdata.GetEpisodeReached(0);
   var ep1r = userdata.GetEpisodeReached(1);
   var ep2r = userdata.GetEpisodeReached(2);
   var ep3r = userdata.GetEpisodeReached(3);
   var ep4r = userdata.GetEpisodeReached(4);
   var ep5r = userdata.GetEpisodeReached(5);
   var ep6r = userdata.GetEpisodeReached(6);
   var ep7r = userdata.GetEpisodeReached(7);
   var ep8r = userdata.GetEpisodeReached(8);
   var ep9r = userdata.GetEpisodeReached(9);
   var menuMC = gui.GetCurrentMC();
   var i = 0;
   while(i < 10)
   {
      var but = eval(menuMC + ".playmenu" + ".e" + i);
      if(i <= ep0)
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "0" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,false);
         };
      }
      else if(i <= ep0r)
      {
         but.gfx.gotoAndStop(3);
         but.num.text = "0" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,true);
         };
      }
      else
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "";
         but.enabled = false;
      }
      i++;
   }
   var i = 10;
   while(i < 20)
   {
      var but = eval(menuMC + ".playmenu" + ".e" + i);
      if(i <= ep1)
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,false);
         };
      }
      else if(i <= ep1r)
      {
         but.gfx.gotoAndStop(3);
         but.num.text = "" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,true);
         };
      }
      else
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "";
         but.enabled = false;
      }
      i++;
   }
   var i = 20;
   while(i < 30)
   {
      var but = eval(menuMC + ".playmenu" + ".e" + i);
      if(i <= ep2)
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,false);
         };
      }
      else if(i <= ep2r)
      {
         but.gfx.gotoAndStop(3);
         but.num.text = "" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,true);
         };
      }
      else
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "";
         but.enabled = false;
      }
      i++;
   }
   var i = 30;
   while(i < 40)
   {
      var but = eval(menuMC + ".playmenu" + ".e" + i);
      if(i <= ep3)
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,false);
         };
      }
      else if(i <= ep3r)
      {
         but.gfx.gotoAndStop(3);
         but.num.text = "" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,true);
         };
      }
      else
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "";
         but.enabled = false;
      }
      i++;
   }
   var i = 40;
   while(i < 50)
   {
      var but = eval(menuMC + ".playmenu" + ".e" + i);
      if(i <= ep4)
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,false);
         };
      }
      else if(i <= ep4r)
      {
         but.gfx.gotoAndStop(3);
         but.num.text = "" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,true);
         };
      }
      else
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "";
         but.enabled = false;
      }
      i++;
   }
   var i = 50;
   while(i < 60)
   {
      var but = eval(menuMC + ".playmenu" + ".e" + i);
      if(i <= ep5)
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,false);
         };
      }
      else if(i <= ep5r)
      {
         but.gfx.gotoAndStop(3);
         but.num.text = "" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,true);
         };
      }
      else
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "";
         but.enabled = false;
      }
      i++;
   }
   var i = 60;
   while(i < 70)
   {
      var but = eval(menuMC + ".playmenu" + ".e" + i);
      if(i <= ep6)
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,false);
         };
      }
      else if(i <= ep6r)
      {
         but.gfx.gotoAndStop(3);
         but.num.text = "" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,true);
         };
      }
      else
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "";
         but.enabled = false;
      }
      i++;
   }
   var i = 70;
   while(i < 80)
   {
      var but = eval(menuMC + ".playmenu" + ".e" + i);
      if(i <= ep7)
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,false);
         };
      }
      else if(i <= ep7r)
      {
         but.gfx.gotoAndStop(3);
         but.num.text = "" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,true);
         };
      }
      else
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "";
         but.enabled = false;
      }
      i++;
   }
   var i = 80;
   while(i < 90)
   {
      var but = eval(menuMC + ".playmenu" + ".e" + i);
      if(i <= ep8)
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,false);
         };
      }
      else if(i <= ep8r)
      {
         but.gfx.gotoAndStop(3);
         but.num.text = "" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,true);
         };
      }
      else
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "";
         but.enabled = false;
      }
      i++;
   }
   var i = 90;
   while(i < 100)
   {
      var but = eval(menuMC + ".playmenu" + ".e" + i);
      if(i <= ep9)
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(1);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,false);
         };
      }
      else if(i <= ep9r)
      {
         but.gfx.gotoAndStop(3);
         but.num.text = "" + i;
         but.onRollOver = function()
         {
            this.gfx.gotoAndStop(2);
         };
         but.onRollOut = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onReleaseOutside = function()
         {
            this.gfx.gotoAndStop(3);
         };
         but.onRelease = function()
         {
            _root.App_PlayEpisodeButtonClicked(this,true);
         };
      }
      else
      {
         but.gfx.gotoAndStop(1);
         but.num.text = "";
         but.enabled = false;
      }
      i++;
   }
}
function App_TickPlayMenu()
{
   App_UpdateMainMenu();
}
function App_PlayEpisodeButtonClicked(but, isCheater)
{
   var _loc2_ = but.num.text;
   if(_loc2_ == "")
   {
      return undefined;
   }
   var _loc1_ = Number(_loc2_);
   if(!userdata.ValidateEpisodeReached(_loc1_))
   {
      gamedata.ResetEpisode();
      console.AddLine("Access Denied: " + _loc1_);
      return undefined;
   }
   var _loc3_;
   if(gamedata.LoadEpisodeNum(_loc1_))
   {
      _loc3_ = new Sound();
      _loc3_.stop();
      APP_IS_PRACTISE = userdata.GetPractiseMode();
      APP_IS_CHEATER = isCheater;
      App_StartNewGame();
   }
}
