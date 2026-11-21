#!/usr/bin/env bash
# Launch AlongSide (creates the venv on first run).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi
# Hide noisy but harmless Qt/Wayland warnings (text-input focus chatter, portal app-ID registration).
export QT_LOGGING_RULES="${QT_LOGGING_RULES:-qt.qpa.wayland.textinput=false;qt.qpa.services=false}"
set +e
.venv/bin/python -m alongside "$@"
code=$?
if [[ $code -ne 0 ]]; then
  echo "AlongSide stopped with exit code $code. Details: ~/.local/share/alongside/alongside.log and crash.log" >&2
fi
exit $code
