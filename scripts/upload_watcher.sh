#!/usr/bin/env bash
# Watch the 5 realizations; the instant one finishes (prints DONE in its log and its
# output dir exists), sync it to S3 and delete the local copy to free staging space.
# S3 upload uses the active default AWS profile (the org account).
set -u
BKT="bsm2-baseline-data-109152774361-us-east-2"
PREFIX="normal_5yr"
RUNS="data/baseline/_runs"          # data -> EFS staging symlink
LOGDIR="logs"
cd /home/sagemaker-user/bsm2-baseline || exit 1

declare -A UP   # uploaded marker
done_count=0
while [ "$done_count" -lt 5 ]; do
  for r in 0 1 2 3 4; do
    rr=$(printf "%02d" "$r")
    [ -n "${UP[$r]:-}" ] && continue
    log="$LOGDIR/real_r${r}.log"
    dir="$RUNS/normal_5yr__baseline__r${rr}"
    if grep -q "DONE" "$log" 2>/dev/null && [ -d "$dir" ]; then
      sz=$(du -sh "$dir" 2>/dev/null | cut -f1)
      echo "[$(date +%H:%M:%S)] r${rr} finished (${sz}); uploading -> s3://$BKT/$PREFIX/realization=r${rr}/"
      if aws s3 sync "$dir/" "s3://$BKT/$PREFIX/realization=r${rr}/" --only-show-errors; then
        echo "[$(date +%H:%M:%S)] r${rr} uploaded OK; deleting local copy"
        rm -rf "$dir"
        UP[$r]=1
        done_count=$((done_count+1))
      else
        echo "[$(date +%H:%M:%S)] r${rr} UPLOAD FAILED (rc=$?); will retry next pass"
      fi
    fi
  done
  [ "$done_count" -lt 5 ] && sleep 15
done
echo "[$(date +%H:%M:%S)] ALL 5 realizations uploaded to s3://$BKT/$PREFIX/ and local staging cleared"
aws s3 ls "s3://$BKT/$PREFIX/" --recursive --human-readable --summarize | tail -8
