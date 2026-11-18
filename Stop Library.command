#!/bin/zsh
project_dir="${0:A:h}"
cd -- "$project_dir" || exit 1
exec "$project_dir/.venv/bin/python" "$project_dir/launcher.py" --stop
