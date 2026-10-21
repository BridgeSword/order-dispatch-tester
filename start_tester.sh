#!/bin/sh
cd "$(dirname "$0")" && exec python3 run.py --port "${PORT:-5088}" "$@"
