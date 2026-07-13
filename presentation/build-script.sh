#!/usr/bin/env bash
# Render the markdown speaker script (script.md) into a readable teleprompter PDF.
# Usage: ./build-script.sh   ->  script.pdf
set -euo pipefail
cd "$(dirname "$0")"
if [[ -z "${CHROME_PATH:-}" ]]; then
  for c in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
           "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
           "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"; do
    [[ -x "$c" ]] && export CHROME_PATH="$c" && break
  done
fi
python3 script_to_html.py script.md script.html
"$CHROME_PATH" --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="script.pdf" "$(pwd)/script.html" 2>/dev/null
echo "→ script.pdf"
