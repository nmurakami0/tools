#!/usr/bin/env bash
set -euo pipefail

# Mac disk cleanup: removes Docker leftovers and well-known safe-to-delete caches.
#
# Default is DRY RUN: it only reports what would be deleted and how large it is.
# Pass --run to actually delete.
#
# Usage:
#   ./mac-disk-cleanup.sh                 # dry run (report only)
#   ./mac-disk-cleanup.sh --run           # delete safe targets
#   ./mac-disk-cleanup.sh --run --docker-all       # also prune ALL unused docker images
#   ./mac-disk-cleanup.sh --run --docker-volumes   # also prune unused docker volumes (DATA LOSS RISK)
#   ./mac-disk-cleanup.sh --run --trash            # also empty ~/.Trash
#   ./mac-disk-cleanup.sh --run --xcode            # also delete Xcode DerivedData / unavailable simulators

DRY_RUN=1
DOCKER_ALL=0
DOCKER_VOLUMES=0
EMPTY_TRASH=0
XCODE=0

for arg in "$@"; do
  case "$arg" in
    --run) DRY_RUN=0 ;;
    --docker-all) DOCKER_ALL=1 ;;
    --docker-volumes) DOCKER_VOLUMES=1 ;;
    --trash) EMPTY_TRASH=1 ;;
    --xcode) XCODE=1 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (see --help)" >&2
      exit 1
      ;;
  esac
done

TOTAL_KB=0

hr() {
  echo "------------------------------------------------------------"
}

section() {
  echo
  hr
  echo "$1"
  hr
}

size_kb() {
  du -sk "$1" 2>/dev/null | awk '{print $1}'
}

human() {
  awk -v kb="$1" 'BEGIN {
    if (kb >= 1048576) printf "%.1fG", kb / 1048576
    else if (kb >= 1024) printf "%.1fM", kb / 1024
    else printf "%dK", kb
  }'
}

# remove_path <path> [label]
remove_path() {
  local target="$1"
  local label="${2:-$1}"
  [ -e "$target" ] || return 0
  local kb
  kb="$(size_kb "$target")"
  [ -z "$kb" ] && kb=0
  TOTAL_KB=$((TOTAL_KB + kb))
  if [ "$DRY_RUN" -eq 1 ]; then
    printf "[dry-run] would delete %-60s %s\n" "$label" "$(human "$kb")"
  else
    printf "deleting  %-60s %s\n" "$label" "$(human "$kb")"
    rm -rf "$target"
  fi
}

# run_cmd <description> <command...>
run_cmd() {
  local desc="$1"
  shift
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] would run: $*"
  else
    echo "running: $* ($desc)"
    "$@" || echo "  -> failed (skipping): $*"
  fi
}

if [ "$DRY_RUN" -eq 1 ]; then
  echo "== Mac Disk Cleanup (DRY RUN - nothing will be deleted, use --run to execute) =="
else
  echo "== Mac Disk Cleanup (EXECUTING) =="
fi

section "1. Docker"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "[docker system df]"
  docker system df || true
  echo

  # Stopped containers, dangling images, unused networks, build cache.
  if [ "$DOCKER_ALL" -eq 1 ]; then
    run_cmd "remove ALL unused images, containers, networks, build cache" \
      docker system prune -af
  else
    run_cmd "remove stopped containers, dangling images, unused networks" \
      docker system prune -f
    echo "  (use --docker-all to also remove all images not used by a container)"
  fi

  run_cmd "clear docker build cache" docker builder prune -af

  if [ "$DOCKER_VOLUMES" -eq 1 ]; then
    echo
    echo "!! Pruning unused volumes - data in volumes not attached to a container WILL BE LOST"
    run_cmd "remove unused docker volumes" docker volume prune -f
  else
    echo "  (use --docker-volumes to also remove unused volumes - check 'docker volume ls' first)"
  fi
else
  echo "docker not running or not installed - skipping (start Docker Desktop to prune)"
fi

section "2. Homebrew"
if command -v brew >/dev/null 2>&1; then
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] would run: brew cleanup --prune=all"
    brew cleanup --prune=all --dry-run 2>/dev/null | tail -n 5 || true
  else
    run_cmd "remove old versions and all cached downloads" brew cleanup --prune=all
  fi
  remove_path "$(brew --cache)" "brew download cache"
else
  echo "brew not found - skipping"
fi

section "3. Package manager caches (npm / pnpm / yarn / pip)"
remove_path "$HOME/.npm/_cacache" "npm cache (~/.npm/_cacache)"
if command -v pnpm >/dev/null 2>&1; then
  run_cmd "remove unreferenced packages from pnpm store" pnpm store prune
fi
remove_path "$HOME/Library/Caches/Yarn" "yarn cache"
remove_path "$HOME/Library/Caches/pip" "pip cache"

section "4. Dev tool caches"
remove_path "$HOME/.gradle/caches" "gradle caches (re-downloaded on next build)"
remove_path "$HOME/Library/Caches/go-build" "go build cache"
remove_path "$HOME/.cache/puppeteer" "puppeteer browser cache"
remove_path "$HOME/Library/Caches/ms-playwright" "playwright browser cache"
remove_path "$HOME/Library/Caches/typescript" "typescript npm metadata cache"
remove_path "$HOME/Library/Caches/node-gyp" "node-gyp headers cache"

section "5. Xcode / Simulator"
if [ "$XCODE" -eq 1 ]; then
  remove_path "$HOME/Library/Developer/Xcode/DerivedData" "Xcode DerivedData"
  if command -v xcrun >/dev/null 2>&1; then
    run_cmd "delete simulators for unavailable runtimes" xcrun simctl delete unavailable
  fi
else
  echo "skipped (use --xcode to delete DerivedData and unavailable simulators)"
fi

section "6. Trash"
if [ "$EMPTY_TRASH" -eq 1 ]; then
  remove_path "$HOME/.Trash" "Trash"
else
  if [ -e "$HOME/.Trash" ]; then
    echo "Trash size: $(du -sh "$HOME/.Trash" 2>/dev/null | awk '{print $1}') (use --trash to empty)"
  fi
fi

section "Summary"
if [ "$DRY_RUN" -eq 1 ]; then
  echo "Reclaimable from file deletions: $(human "$TOTAL_KB") (docker/brew prune amounts not included)"
  echo "Run again with --run to delete."
else
  echo "Deleted from file paths: $(human "$TOTAL_KB") (plus whatever docker/brew pruned)"
  echo "Current free space:"
  df -h / | tail -n 1
fi

echo
echo "Done."
