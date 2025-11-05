#!/bin/bash

if [ "$1" == "--no" ]; then
    rm /root/.local/share/ruffle/SharedObjects/localhost/n_v14b_userdata.sol
else
   cp n_tas.sol /root/.local/share/ruffle/SharedObjects/localhost/n_v14b_userdata.sol
fi
