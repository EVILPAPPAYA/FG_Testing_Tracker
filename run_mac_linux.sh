#!/usr/bin/env bash
# Start the FG Testing Tracker on Mac or Linux.
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed. Download it from https://www.python.org/downloads/"
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "First run: setting things up. This takes a minute..."
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --quiet --disable-pip-version-check -r requirements.txt

python app.py
