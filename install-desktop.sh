#!/usr/bin/env bash
# Add AlongSide to the GNOME app launcher, with its icon. Re-run after moving the folder.
set -euo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
icons="$HOME/.local/share/icons/hicolor"

# Icon at every size GNOME may ask for, plus the scalable SVG.
for size in 16 24 32 48 64 128 256 512; do
  install -Dm644 "$dir/assets/alongside-$size.png" "$icons/${size}x${size}/apps/alongside.png"
done
install -Dm644 "$dir/assets/alongside.svg" "$icons/scalable/apps/alongside.svg"
gtk-update-icon-cache -f -t "$icons" >/dev/null 2>&1 || true

mkdir -p ~/.local/share/applications
cat > ~/.local/share/applications/alongside.desktop <<DESK
[Desktop Entry]
Type=Application
Name=AlongSide
GenericName=Mock Interview Practice
Comment=Practise tough IT interviews with an AI interviewer
Exec="$dir/run.sh"
Path=$dir
Icon=alongside
Terminal=false
Categories=Development;
Keywords=interview;mock;practice;coding;system design;
StartupNotify=true
StartupWMClass=alongside
DESK
update-desktop-database ~/.local/share/applications >/dev/null 2>&1 || true
echo "Installed. Search for 'AlongSide' in Activities."
