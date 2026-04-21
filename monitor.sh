#!/bin/bash
# Monitor script: tracks file changes in the Xmoney directory
# Run: bash monitor.sh

WATCH_DIR="D:/project/AAPersonalInnovation/Xmoney"
LOG_FILE="$WATCH_DIR/monitor_log.txt"
SNAPSHOT_FILE="$WATCH_DIR/.file_snapshot.txt"

echo "=== Monitor started at $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG_FILE"

while true; do
    # Take current snapshot (excluding .git, imgs, .idea, monitor files)
    find "$WATCH_DIR" -type f \
        -not -path '*/.git/*' \
        -not -path '*/imgs/*' \
        -not -path '*/.idea/*' \
        -not -name 'monitor_log.txt' \
        -not -name '.file_snapshot.txt' \
        -not -name 'monitor.sh' \
        -printf '%T@ %p\n' 2>/dev/null | sort -n > "$SNAPSHOT_FILE.new"
    
    if [ -f "$SNAPSHOT_FILE" ]; then
        DIFF=$(diff "$SNAPSHOT_FILE" "$SNAPSHOT_FILE.new" 2>/dev/null)
        if [ -n "$DIFF" ]; then
            echo "--- Changes detected at $(date '+%Y-%m-%d %H:%M:%S') ---" >> "$LOG_FILE"
            echo "$DIFF" >> "$LOG_FILE"
            echo "" >> "$LOG_FILE"
        fi
    fi
    
    mv "$SNAPSHOT_FILE.new" "$SNAPSHOT_FILE"
    sleep 120  # Check every 2 minutes
done
