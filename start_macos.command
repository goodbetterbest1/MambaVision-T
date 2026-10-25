#!/bin/sh
cd -- "$(dirname -- "$0")" || exit 1
python3 run_local.py "$@"
printf '\n服务已停止。按回车关闭窗口。'
read -r _
