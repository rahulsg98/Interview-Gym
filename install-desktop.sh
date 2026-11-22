#!/usr/bin/env bash
# Add Interview Gym to the GNOME app launcher, with its icon. Re-run after moving the folder.
set -euo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
icons="$HOME/.local/share/icons/hicolor"
apps="$HOME/.local/share/applications"

# Icon at every size GNOME may ask for, plus the scalable SVG.
for size in 16 24 32 48 64 128 256 512; do
  install -Dm644 "$dir/assets/interview-gym-$size.png" "$icons/${size}x${size}/apps/interview-gym.png"
done
install -Dm644 "$dir/assets/interview-gym.svg" "$icons/scalable/apps/interview-gym.svg"
gtk-update-icon-cache -f -t "$icons" >/dev/null 2>&1 || true

mkdir -p "$apps"
# The app used to be called AlongSide: set its old launcher aside so it doesn't show up twice.
if [[ -f "$apps/alongside.desktop" ]]; then
  mv -f "$apps/alongside.desktop" "$apps/alongside.desktop.bak"
fi
cat > "$apps/interview-gym.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Interview Gym
GenericName=Mock Interview Practice
Comment=Practise tough IT interviews with an AI interviewer
Exec="$dir/run.sh"
Path=$dir
Icon=interview-gym
Terminal=false
Categories=Development;
Keywords=interview;gym;mock;practice;coding;system design;AlongSide;
StartupNotify=true
StartupWMClass=interview-gym
DESK
update-desktop-database "$apps" >/dev/null 2>&1 || true
echo "Installed. Search for 'Interview Gym' in Activities."
