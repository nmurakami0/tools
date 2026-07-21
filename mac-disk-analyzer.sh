#!/usr/bin/env bash
set -euo pipefail

echo "== Mac Disk Usage Analyzer =="
echo

hr() {
  echo "------------------------------------------------------------"
}

section() {
  echo
  hr
  echo "$1"
  hr
}

safe_du_top() {
  local target="$1"
  local depth="${2:-1}"
  if [ -e "$target" ]; then
    du -h -d "$depth" "$target" 2>/dev/null | sort -hr | head -n 30
  else
    echo "Not found: $target"
  fi
}

section "1. Home directory top usage"
du -h -d 1 ~ 2>/dev/null | sort -hr | head -n 30

section "2. ~/Library breakdown"
safe_du_top "$HOME/Library" 1

section "3. ~/Library/Application Support breakdown"
safe_du_top "$HOME/Library/Application Support" 1

section "4. ~/Library/Caches breakdown"
safe_du_top "$HOME/Library/Caches" 1

section "5. ~/Developer breakdown"
safe_du_top "$HOME/Developer" 2

section "6. Common large dev caches"
for p in \
  "$HOME/.gradle" \
  "$HOME/.m2" \
  "$HOME/.npm" \
  "$HOME/.pnpm-store" \
  "$HOME/.cache" \
  "$HOME/.ivy2" \
  "$HOME/.coursier" \
  "$HOME/.sdkman" \
  "$HOME/.rustup" \
  "$HOME/.cargo" \
  "$HOME/.docker" \
  "$HOME/.local" \
  "$HOME/Downloads"
do
  if [ -e "$p" ]; then
    du -sh "$p" 2>/dev/null
  fi
done | sort -hr

section "7. Xcode / Simulator"
for p in \
  "$HOME/Library/Developer/Xcode/DerivedData" \
  "$HOME/Library/Developer/Xcode/Archives" \
  "$HOME/Library/Developer/CoreSimulator" \
  "$HOME/Library/Developer/XCTestDevices"
do
  if [ -e "$p" ]; then
    du -sh "$p" 2>/dev/null
  fi
done | sort -hr

section "8. Docker Desktop related"
for p in \
  "$HOME/Library/Containers/com.docker.docker" \
  "$HOME/Library/Group Containers/group.com.docker" \
  "$HOME/.docker"
do
  if [ -e "$p" ]; then
    du -sh "$p" 2>/dev/null
  fi
done | sort -hr

if command -v docker >/dev/null 2>&1; then
  echo
  echo "[docker system df]"
  docker system df || true

  echo
  echo "[largest docker volumes path if exists]"
  find "$HOME/Library/Containers/com.docker.docker" -type d -name volumes 2>/dev/null | while read -r vdir; do
    du -h -d 2 "$vdir" 2>/dev/null | sort -hr | head -n 20
  done
fi

section "9. Top 30 large files in home directory (excluding obvious noisy system paths)"
find ~ \
  -path "$HOME/Library/Caches" -prune -o \
  -path "$HOME/.Trash" -prune -o \
  -type f -print0 2>/dev/null |
  xargs -0 du -h 2>/dev/null |
  sort -hr |
  head -n 30

section "10. node_modules directories"
find ~ \
  -path "$HOME/Library" -prune -o \
  -type d -name node_modules -print0 2>/dev/null |
  xargs -0 du -sh 2>/dev/null |
  sort -hr |
  head -n 50

echo
section "11. Suggested cleanup targets"
cat <<'EOX'
Check these first if they are large:
- ~/Downloads
- ~/Library/Application Support
- ~/Library/Caches
- ~/Library/Containers
- ~/Library/Developer/Xcode/DerivedData
- ~/Library/Developer/CoreSimulator
- ~/.gradle
- ~/.npm
- ~/.pnpm-store
- Docker unused images / volumes / build cache
- old node_modules in unused repositories
EOX

echo
echo "Done."
