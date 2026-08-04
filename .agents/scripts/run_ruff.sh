#!/bin/bash
# Find modified/untracked Python files and run ruff on them
files=$(git status --porcelain | awk '{print $2}' | grep '\.py$')
if [ -n "$files" ]; then
    # Move to the project root directory
    cd ..
    RUFF=".venv/bin/ruff"
    if [ ! -f "$RUFF" ]; then
        RUFF="ruff"
    fi
    for f in $files; do
        if [ -f "$f" ]; then
            $RUFF check --fix "$f" >/dev/null 2>&1
            $RUFF format "$f" >/dev/null 2>&1
        fi
    done
fi
# Output valid JSON as per the hook contract
echo "{}"
