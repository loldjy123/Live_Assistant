#!/bin/zsh
project_dir="${0:A:h}"
cd -- "$project_dir" || exit 1
if [[ ! -x "$project_dir/.venv/bin/python" ]]; then
    print 'Missing .venv. Follow the setup steps in README.md first.'
    exit 1
fi
exec "$project_dir/.venv/bin/python" "$project_dir/launcher.py"
