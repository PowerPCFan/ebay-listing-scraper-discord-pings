#!/usr/bin/env bash

set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <file>"
  exit 1
fi

FILE="$1"

if [ ! -f "$FILE" ]; then
  echo "File not found: $FILE"
  exit 1
fi


grep -nE ':[[:space:]]*[0-9]{15,}([[:space:]]*[,}]|[[:space:]]*$)' "$FILE" || true
