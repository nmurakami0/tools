#!/usr/bin/env bash
#
# analyze-actions-cost.sh — Break down elw-llc GitHub Actions cost.
#
# The org is on GitHub's enhanced billing platform: the classic
# /orgs/{org}/settings/billing/actions endpoint is gone (HTTP 410), and the
# /runs/{id}/timing endpoint reports total_ms: 0. So:
#   - repo/SKU cost  -> /organizations/{org}/settings/billing/usage
#   - per-workflow   -> Actions runs + jobs API (sum of per-job durations)
#
# Requires: gh (authenticated), jq, bc.
#
# Usage:
#   ./analyze-actions-cost.sh sku       <year> <month>
#   ./analyze-actions-cost.sh repos     <year> <month>
#   ./analyze-actions-cost.sh workflows <owner/repo> <year> <month> [sample=15]
#
# Examples:
#   ./analyze-actions-cost.sh repos 2026 7
#   ./analyze-actions-cost.sh workflows elw-llc/drivesfa-management-server 2026 7
set -euo pipefail

ORG="${ORG:-elw-llc}"

last_day() { # year month -> last day of month (handles leap Feb)
  local y=$1 m=$((10#$2))
  case $m in
    1|3|5|7|8|10|12) echo 31 ;;
    4|6|9|11)        echo 30 ;;
    2) if (( y % 4 == 0 && (y % 100 != 0 || y % 400 == 0) )); then echo 29; else echo 28; fi ;;
  esac
}

cmd_sku() { # year month
  local y=$1 m=$2
  echo "=== ${ORG} usage by product/SKU — ${y}-$(printf %02d "$m") (net USD) ==="
  gh api "/organizations/${ORG}/settings/billing/usage?year=${y}&month=$((10#$m))" 2>/dev/null \
  | jq -r '.usageItems
      | group_by(.product + " / " + .sku)
      | map({k:(.[0].product + " / " + .[0].sku), net:(map(.netAmount)|add)})
      | sort_by(-.net)[] | "\((.net*100|round)/100)\t\(.k)"'
}

cmd_repos() { # year month
  local y=$1 m=$2
  echo "=== ${ORG} Actions Linux minutes by repo — ${y}-$(printf %02d "$m") ==="
  printf "%10s  %10s  %s\n" "net_USD" "minutes" "repo"
  gh api "/organizations/${ORG}/settings/billing/usage?year=${y}&month=$((10#$m))" 2>/dev/null \
  | jq -r '[.usageItems[] | select(.product=="actions" and .sku=="Actions Linux")]
      | group_by(.repositoryName)
      | map({repo:.[0].repositoryName, min:(map(.quantity)|add), net:(map(.netAmount)|add)})
      | sort_by(-.net)[] | "\((.net*100|round)/100)\t\(.min|round)\t\(.repo)"' \
  | awk -F'\t' '{printf "%10s  %10s  %s\n", $1, $2, $3}'
}

cmd_workflows() { # owner/repo year month [sample]
  local repo=$1 y=$2 m=$3 sample="${4:-15}"
  local mm ld from to
  mm=$(printf %02d "$m"); ld=$(last_day "$y" "$m")
  from="${y}-${mm}-01"; to="${y}-${mm}-${ld}"
  echo "=== ${repo} billable minutes by workflow — ${from}..${to} (sample=${sample}/workflow) ==="
  printf "%-34s %6s %7s %12s %12s\n" "WORKFLOW" "runs" "sampled" "avg_min/run" "EST_min/mo"

  # iterate active workflows
  gh api "/repos/${repo}/actions/workflows" --jq '.workflows[] | select(.state=="active") | "\(.id)\t\(.name)"' 2>/dev/null \
  | while IFS=$'\t' read -r wid name; do
      local cnt; cnt=$(gh api "/repos/${repo}/actions/workflows/${wid}/runs?created=${from}..${to}&per_page=1" --jq '.total_count' 2>/dev/null || echo 0)
      [ "${cnt:-0}" -eq 0 ] && continue
      local tot=0 k=0 m_run
      while read -r rid; do
        [ -z "$rid" ] && continue
        m_run=$(gh api "/repos/${repo}/actions/runs/${rid}/jobs?per_page=100" \
          --jq '[.jobs[] | select(.completed_at!=null and .started_at!=null)
                 | ((.completed_at|fromdateiso8601)-(.started_at|fromdateiso8601))
                 | ((.+59)/60|floor)] | add // 0' 2>/dev/null || echo "")
        if [ -n "$m_run" ]; then tot=$((tot+m_run)); k=$((k+1)); fi
      done < <(gh api "/repos/${repo}/actions/workflows/${wid}/runs?status=completed&created=${from}..${to}&per_page=${sample}" --jq '.workflow_runs[].id' 2>/dev/null)
      local avg=0 est=0
      if [ "$k" -gt 0 ]; then avg=$(echo "scale=1; $tot/$k" | bc); est=$(echo "scale=0; $tot/$k*$cnt/1" | bc); fi
      printf "%-34s %6s %7s %12s %12s\n" "$name" "$cnt" "$k" "$avg" "$est"
    done
}

case "${1:-}" in
  sku)       shift; cmd_sku "$@" ;;
  repos)     shift; cmd_repos "$@" ;;
  workflows) shift; cmd_workflows "$@" ;;
  *) grep -E '^#( |!|$)' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
