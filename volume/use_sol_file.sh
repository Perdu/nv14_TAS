#!/bin/bash

if [ "$1" == "--no" ]; then
    rm /root/.local/share/ruffle/SharedObjects/localhost/n_v14b_userdata.sol
elif [ "$1" == "--override" ]; then
   cp n_tas_lowscores.sol /root/.local/share/ruffle/SharedObjects/localhost/n_v14b_userdata.sol
else
   cp n_tas.sol /root/.local/share/ruffle/SharedObjects/localhost/n_v14b_userdata.sol
fi
