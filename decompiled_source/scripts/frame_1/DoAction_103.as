function EpisodeData(epname, code, levelList)
{
   this.epname = epname;
   this.code = code;
   this.levelList = levelList;
}
function LevelData(levname, levStr)
{
   this.levname = levname;
   this.levStr = levStr;
}
function MenuDemoData(epID, levNum, demoStr)
{
   this.epID = epID;
   this.levNum = levNum;
   this.demoStr = demoStr;
}
function HelpDemoData(objStr, demoList)
{
   this.objStr = objStr;
   this.demoList = demoList;
}
