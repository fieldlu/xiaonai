#!/bin/bash
cd /opt/xiaonai || exit 1
python3 bot.py >> bot.log 2>&1
echo started
