#!/usr/bin/env bash
# Build the thesis-defense deck from Markdown to PDF (and optionally HTML).
# Requires Marp CLI:  brew install marp-cli   (or  npm i -g @marp-team/marp-cli)
#
# Usage:
#   ./build.sh         # -> deck.pdf
#   ./build.sh html    # -> deck.html (good for live presenting / presenter view)
#   ./build.sh watch   # live-rebuild HTML on save
set -euo pipefail
cd "$(dirname "$0")"

THEME="themes/worldview-light.css"
SRC="deck.md"

# Marp renders via a headless Chromium. If no Chrome/Edge/Firefox is on PATH,
# fall back to any Chromium-family browser we can find (e.g. Brave on macOS).
if [[ -z "${CHROME_PATH:-}" ]]; then
  for cand in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
    "/Applications/Chromium.app/Contents/MacOS/Chromium"; do
    [[ -x "$cand" ]] && export CHROME_PATH="$cand" && break
  done
fi

case "${1:-pdf}" in
  pdf)   marp "$SRC" --theme-set "$THEME" --html --allow-local-files -o deck.pdf  && echo "→ deck.pdf" ;;
  html)  marp "$SRC" --theme-set "$THEME" --html --allow-local-files -o deck.html && echo "→ deck.html" ;;
  watch) marp "$SRC" --theme-set "$THEME" --html --allow-local-files --watch --html -o deck.html ;;
  *)     echo "usage: ./build.sh [pdf|html|watch]" && exit 1 ;;
esac
