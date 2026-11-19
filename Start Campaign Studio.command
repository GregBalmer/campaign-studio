#!/bin/sh
# Double-click this file in Finder to start Campaign Studio.
# It runs start.py in this folder: the first time it sets up what it needs
# (about 30 seconds), then it opens the app in your browser.
# Keep this window open while you use the app. Closing it stops the app.

cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo ""
  echo "Campaign Studio needs Python 3, and this computer doesn't have it."
  echo "Install it from https://www.python.org/downloads/ and double-click this file again."
  echo ""
  if [ "$1" != "--check" ]; then
    echo "Press Return to close this window."
    read -r _
  fi
  exit 1
fi

python3 start.py "$@"
status=$?
if [ "$status" -ne 0 ] && [ "$status" -ne 130 ] && [ "$1" != "--check" ]; then
  echo ""
  echo "Press Return to close this window."
  read -r _
fi
exit "$status"
