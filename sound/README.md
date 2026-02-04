# Sound

Getting sound to work in libTAS is not really useful, as you don't need sound during the TASing process (it breaks savestates) and sound in encoding will work regardless.

If you want it regardless, you can use the [Dockerfile_sound](Dockerfile_sound) I made and run it with:

```
docker run -it --rm -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix -v $HOME/.Xauthority:/root/.Xauthority:rw --net=host -v /home/$whoami/nv14_TAS/volume:/home/taser/tas/ -v /run/user/$UID/pulse:/run/user/$UID/pulse -e PULSE_SERVER=unix:/run/user/$UID/pulse/native -v /etc/machine-id:/etc/machine-id:ro --group-add audio --cap-add=cap_checkpoint_restore libtas_sound
```

(this is more restrictive as it's not running with root user inside the container)
