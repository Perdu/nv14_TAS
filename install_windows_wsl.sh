#!/bin/bash

# Adaptation of the Dockerfile (hopefully up-to-date) to install everything inside WSL

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

sudo dpkg --add-architecture i386
sudo apt-get update 

# Dependencies
  # libTAS
    # main
sudo apt-get -y install build-essential automake pkg-config libx11-dev libx11-xcb-dev qtbase5-dev libsdl2-dev libxcb1-dev libxcb-keysyms1-dev libxcb-xkb-dev libxcb-cursor-dev libxcb-randr0-dev libudev-dev libasound2-dev libavutil-dev libswresample-dev ffmpeg liblua5.4-dev libcap-dev libxcb-xinput-dev

    # HUD / fonts
sudo apt-get -y install libfreetype6-dev libfontconfig1-dev
sudo apt-get -y install fonts-liberation

    # i386
sudo apt-get -y install g++-multilib
sudo apt-get -y install libx11-6:i386 libx11-dev:i386 libx11-xcb1:i386 libx11-xcb-dev:i386 libasound2:i386 libasound2-dev:i386 libavutil57:i386 libswresample4:i386 libfreetype6:i386 libfreetype6-dev:i386 libfontconfig1:i386 libfontconfig1-dev:i386

    # utils
sudo apt-get -y install git wget

# Ruffle
sudo apt-get install -y \
          libasound2-dev \
          libudev-dev \
          default-jre-headless \
          g++
sudo apt-get install -y curl
sudo curl https://sh.rustup.rs -sSf | sh -s -- -y

# Installs
    mkdir /home/$(whoami)/src

  # Ruffle
    cd /home/$(whoami)/ && git clone https://github.com/ruffle-rs/ruffle.git
    # pin version
    cd /home/$(whoami)/ruffle && git checkout fa9c6627bd86511de1b710dcf42708dc55c44e3e
    PATH="/home/$(whoami)/.cargo/bin:${PATH}"
    cd /home/$(whoami)/ruffle && cargo build --release --package=ruffle_desktop
    # RUN cd /home/$(whoami)/ruffle && make install

  # libTAS
    # RUN cd /home/$(whoami)/ && git clone https://github.com/clementgallet/libTAS.git
    cd /home/$(whoami)/ && git clone https://github.com/Perdu/libTAS.git
    cd /home/$(whoami)/libTAS && ./build.sh --with-i386
    cd /home/$(whoami)/libTAS/build && sudo make install

# n-related commands
  cd "$SCRIPT_DIR"
  cp external/n_v14.swf volume/
  # LibTAS config
  cp docker/ruffle_desktop.ini /home/$(whoami)/.config/libTAS/
  cp docker/libTAS.ini /home/$(whoami)/.config/libTAS/
  # Fixing the determinism bug: by adding the libopenh264 file manually, we avoid having to open ruffle manually every time
  cp external/libopenh264-2.4.1-linux64.7.so /home/$(whoami)/.cache/ruffle/video/
  # Use the .sol file. Remove for encoding
  cp volume/n_tas.sol /home/$(whoami)/.local/share/ruffle/SharedObjects/localhost/n_v14b_userdata.sol
