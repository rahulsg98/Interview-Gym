#!/usr/bin/env bash
# Add AlongSide to the GNOME app launcher.
set -euo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ~/.local/share/applications
cat > ~/.local/share/applications/alongside.desktop <<DESK
[Desktop Entry]
Type=Application
Name=AlongSide
Comment=Mock interview practice
Exec="$dir/run.sh"
Icon=audio-input-microphone
Terminal=false
Categories=Development;
StartupWMClass=alongside
DESK
echo "Installed. Search for 'AlongSide' in Activities."
