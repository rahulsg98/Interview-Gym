#!/usr/bin/env bash
# Launch Interview Gym (creates the venv on first run).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -q --upgrade pip
  .venv/bin/python -m pip install -q -r requirements.txt
fi
# Natural voice engine: kokoro-onnx caps Python <3.14 in its metadata but runs fine on newer Python.
if ! .venv/bin/python -c "import kokoro_onnx" 2>/dev/null; then
  .venv/bin/python -m pip install -q --ignore-requires-python --no-deps "kokoro-onnx==0.6.1" || true
fi
# Hide noisy but harmless Qt/Wayland warnings (text-input focus chatter, portal app-ID registration).
export QT_LOGGING_RULES="${QT_LOGGING_RULES:-qt.qpa.wayland.textinput=false;qt.qpa.services=false}"
set +e
.venv/bin/python -m interview_gym "$@"
code=$?
if [[ $code -ne 0 ]]; then
  echo "Interview Gym stopped with exit code $code. Details: ~/.local/share/interview-gym/interview-gym.log and crash.log" >&2
fi
exit $code
