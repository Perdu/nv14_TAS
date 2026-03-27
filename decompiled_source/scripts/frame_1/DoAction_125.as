function CreateMC(linkName, instanceName)
{
   var _loc1_ = gfx.GetNextDepth_Front();
   if(linkName == "EMPTY_MC")
   {
      return mcBuffer.createEmptyMovieClip(instanceName,_loc1_);
   }
   if(linkName == "TEXT_MC")
   {
      return mcBuffer.createTextField(instanceName,_loc1_,0,0,100,100);
   }
   return mcBuffer.attachMovie(linkName,instanceName + _loc1_,_loc1_);
}
DestroyMC = function(mc)
{
   mc.swapDepths(1048000);
   mc.removeMovieClip();
};
