EPISODE_FINAL0 = 9;
EPISODE_FINAL1 = 19;
EPISODE_FINAL2 = 29;
EPISODE_FINAL3 = 39;
EPISODE_FINAL4 = 49;
EPISODE_FINAL5 = 59;
EPISODE_FINAL6 = 69;
EPISODE_FINAL7 = 79;
EPISODE_FINAL8 = 89;
EPISODE_FINAL9 = 99;
NinjaData.prototype.BuildGameData = function()
{
   this.BuildGameData_Set0();
   this.BuildGameData_Set1();
   this.BuildGameData_Set2();
   this.BuildGameData_Set3();
   this.BuildGameData_Set4();
   this.BuildGameData_Set5();
   this.BuildGameData_Set6();
   this.BuildGameData_Set7();
   this.BuildGameData_Set8();
   this.BuildGameData_Set9();
   this.levelList = this.episodeList[0].levelList;
   this.BuildGameData_MenuDemos();
   this.BuildGameData_HelpDemos();
};
