function InitApp()
{
   gfx = new NinjaGraphicsSystem();
   particles = new ParticleManager(gfx.bufferList[LAYER_PARTICLES_FRONT],gfx.bufferList[LAYER_PARTICLES_BACK]);
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
