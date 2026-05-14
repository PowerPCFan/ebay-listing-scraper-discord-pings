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
echo "Changes:"
git diff --no-index --color=always -- "$FILE.bak" "$FILE" || true
