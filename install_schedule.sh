#!/bin/bash
# Adds a weekly run of run_update.sh (Mondays 09:00) to your crontab. Run once.
# Remove it later with:  crontab -l | grep -v run_update.sh | crontab -
DIR="$(cd "$(dirname "$0")" && pwd)"
LINE="0 9 * * 1 cd \"$DIR\" && ./run_update.sh >/dev/null 2>&1"
( crontab -l 2>/dev/null | grep -v "run_update.sh"; echo "$LINE" ) | crontab -
echo "Scheduled. Your crontab now contains:"
crontab -l | grep run_update.sh
case "$DIR" in
  "$HOME/Downloads"*|"$HOME/Desktop"*|"$HOME/Documents"*)
    echo ""
    echo "NOTE: this project is inside Downloads/Desktop/Documents. macOS blocks scheduled jobs from"
    echo "reading these folders unless cron has Full Disk Access:"
    echo "  System Settings > Privacy & Security > Full Disk Access > + > press Cmd+Shift+G,"
    echo "  type /usr/sbin/cron, Open, and switch it on."
    echo "Check it worked after the next Monday 09:00 run in the app (Data quality tab) or: tail logs/update.log";;
esac
