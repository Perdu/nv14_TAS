FROM debian:12

# Extended from https://github.com/clementgallet/libTAS/blob/master/Dockerfile

# update
  RUN dpkg --add-architecture i386
  RUN apt-get update 

# libtas
  # dependencies
    # main
      RUN apt-get -y install build-essential automake pkg-config libx11-dev libx11-xcb-dev qtbase5-dev libsdl2-dev libxcb1-dev libxcb-keysyms1-dev libxcb-xkb-dev libxcb-cursor-dev libxcb-randr0-dev libudev-dev libasound2-dev libavutil-dev libswresample-dev ffmpeg liblua5.4-dev libcap-dev libxcb-xinput-dev

    # HUD
      RUN apt-get -y install libfreetype6-dev libfontconfig1-dev

    # fonts
      RUN apt-get -y install libfreetype6-dev libfontconfig1-dev
      RUN apt-get -y install fonts-liberation

    # i386
      RUN apt-get -y install g++-multilib
      RUN apt-get -y install libx11-6:i386 libx11-dev:i386 libx11-xcb1:i386 libx11-xcb-dev:i386 libasound2:i386 libasound2-dev:i386 libavutil57:i386 libswresample4:i386 libfreetype6:i386 libfreetype6-dev:i386 libfontconfig1:i386 libfontconfig1-dev:i386


  # install libTAS
    RUN apt-get -y install git wget
    RUN mkdir /root/src
    RUN cd /root/src && git clone https://github.com/clementgallet/libTAS.git
    # pin version (this version works)
    RUN cd /root/src/libTAS && git checkout v1.4.7
    RUN cd /root/src/libTAS && ./build.sh --with-i386
    RUN cd /root/src/libTAS/build && make install

# ruffle
  RUN apt-get update && apt-get install -y \
        libasound2-dev \
        libudev-dev \
        default-jre-headless \
        g++
  RUN apt-get install -y curl
  RUN curl https://sh.rustup.rs -sSf | sh -s -- -y
  RUN cd /root/src/ && git clone https://github.com/ruffle-rs/ruffle.git
  # pin version
  RUN cd /root/src/ruffle && git checkout fa9c6627bd86511de1b710dcf42708dc55c44e3e
  # RUN apt-get install -y cargo
  ENV PATH="/root/.cargo/bin:${PATH}"
  RUN cd /root/src/ruffle && cargo build --release --package=ruffle_desktop
  # RUN cd /root/src/ruffle && make install

# n-related commands
  COPY external/n_v14.swf /home/
  RUN echo "/root/src/libTAS/build/AppDir/usr/bin/libTAS /root/src/ruffle/target/release/ruffle_desktop -g gl --no-gui /home/n_v14.swf &" > /root/.bash_history
  COPY docker/ruffle_desktop.ini /root/.config/libTAS/
  COPY docker/libTAS.ini /root/.config/libTAS/

# run
  CMD bash
