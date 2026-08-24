#!/bin/sh
set -eu
cd "$(dirname "$0")/.." || exit 1
exec env PYTHONDONTWRITEBYTECODE=1 python3 -B 运行入口/启动.py
