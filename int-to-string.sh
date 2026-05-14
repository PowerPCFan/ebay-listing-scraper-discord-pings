#!/usr/bin/env bash

set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <config-file>"
  exit 1
fi

FILE="$1"

if [ ! -f "$FILE" ]; then
  echo "File not found: $FILE"
  exit 1
fi

sed -E -i.bak 's/(:[[:space:]]*)([0-9]{15,})([[:space:]]*[,}])/\1"\2"\3/g' "$FILE"

echo "Done. Updated: $FILE"
echo "Backup saved: $FILE.bak"

if cmp -s "$FILE.bak" "$FILE"; then
  echo "No changes were needed."
  exit 0
fi

echo

read -p "Changes were made. Do you want to see the diff? (Y/n) " showdiff
if [[ "${showdiff:-Y}" =~ ^[Yy]([eE][sS])?$ ]]; then
  read -p "Would you like to use a pager? (Y/n) " usepager
  if [[ "${usepager:-Y}" =~ ^[Yy]([eE][sS])?$ ]]; then
    echo "Changes:"
    git diff --no-index --color=always -- "$FILE.bak" "$FILE" || true
  else
    echo "Changes (no pager):"
    git --no-pager diff --no-index --color=always -- "$FILE.bak" "$FILE" || true
  fi
else
  echo "Diff skipped."
  exit 0
fi

