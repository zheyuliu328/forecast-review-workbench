#!/bin/sh
set -eu
frw_directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$frw_directory"
if [ ! -x .venv/bin/forecast-review ]; then
    python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10 or newer is required"'
    python3 -m venv .venv
    .venv/bin/python -m pip install .
fi
exec .venv/bin/forecast-review
