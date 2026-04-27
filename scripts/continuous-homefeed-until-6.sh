#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

MAX_ACCOUNTS="${MAX_ACCOUNTS:-30}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-3600}"
DB_PATH="${DB_PATH:-./data/red_crawler.db}"
OUTPUT_ROOT="${OUTPUT_ROOT:-./output/continuous-homefeed}"
LOG_PATH="${LOG_PATH:-./logs/continuous-homefeed.log}"
UNTIL="${UNTIL:-}"

if [ -z "$UNTIL" ]; then
  current_hour="$(date +%H)"
  if [ "$current_hour" -lt 6 ]; then
    UNTIL="$(date +%Y-%m-%d) 06:00:00"
  else
    UNTIL="$(date -d tomorrow +%Y-%m-%d) 06:00:00"
  fi
fi

cutoff_epoch="$(date -d "$UNTIL" +%s)"
mkdir -p "$(dirname "$LOG_PATH")" "$OUTPUT_ROOT"

echo "continuous-homefeed: started at $(date '+%Y-%m-%d %H:%M:%S %Z')" | tee -a "$LOG_PATH"
echo "continuous-homefeed: cutoff $UNTIL" | tee -a "$LOG_PATH"
echo "continuous-homefeed: max-accounts $MAX_ACCOUNTS, interval ${INTERVAL_SECONDS}s" | tee -a "$LOG_PATH"
echo "continuous-homefeed: db-path $DB_PATH" | tee -a "$LOG_PATH"

round=1
while [ "$(date +%s)" -lt "$cutoff_epoch" ]; do
  round_start="$(date +%s)"
  ts="$(date +%Y%m%d-%H%M%S)"
  outdir="$OUTPUT_ROOT/$ts"
  mkdir -p "$outdir"

  echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] round $round start output=$outdir" | tee -a "$LOG_PATH"

  set +e
  env UV_CACHE_DIR=/tmp/uv-cache uv run red-crawler crawl-homefeed \
    --max-accounts "$MAX_ACCOUNTS" \
    --db-path "$DB_PATH" \
    --output-dir "$outdir" \
    ${EXTRA_ARGS:-} \
    2>&1 | tee -a "$LOG_PATH"
  exit_code="${PIPESTATUS[0]}"
  set -e

  echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] round $round exit_code=$exit_code" | tee -a "$LOG_PATH"

  round="$((round + 1))"
  next_start="$((round_start + INTERVAL_SECONDS))"
  now="$(date +%s)"

  if [ "$next_start" -gt "$cutoff_epoch" ] || [ "$now" -ge "$cutoff_epoch" ]; then
    break
  fi

  sleep_seconds="$((next_start - now))"
  if [ "$sleep_seconds" -gt 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] sleeping ${sleep_seconds}s" | tee -a "$LOG_PATH"
    sleep "$sleep_seconds"
  fi
done

echo "continuous-homefeed: finished at $(date '+%Y-%m-%d %H:%M:%S %Z')" | tee -a "$LOG_PATH"
