#!/usr/bin/env bash

set -eu

MIN_LENGTH=1

if [[ $1 == --min-length ]]; then
  MIN_LENGTH="$2"
  shift 2
fi

FILE="${1:?Usage: $0 [--min-length LENGTH] <file>}"

if [ ! -f "$FILE" ]; then
  echo "File not found: $FILE"
  exit 1
fi

python3 -c '
import re
import sys

path = sys.argv[1]
min_length = int(sys.argv[2])

str_re = re.compile(r"\"(?:\\\\.|[^\"\\\\])*\"")
num_re = re.compile(r"-?\d+")

with open(path, "r", encoding="utf-8") as f:
    for lineno, original in enumerate(f, 1):
        line = original.rstrip("\n")
        masked = str_re.sub("\"\"", line)
        has_match = False
        for m in num_re.finditer(masked):
            start, end = m.span()
            num_str = masked[start:end]

            prevc = ""
            i = start - 1
            while i >= 0:
                c = masked[i]
                if not c.isspace():
                    prevc = c
                    break
                i -= 1

            nextc = ""
            i = end
            while i < len(masked):
                c = masked[i]
                if not c.isspace():
                    nextc = c
                    break
                i += 1

            if nextc != ":" and prevc in (":", ",", "[", "") and len(num_str) >= min_length:
                has_match = True
                break

        if has_match:
            print(f"{lineno}:{line}")
' "$FILE" "$MIN_LENGTH"
