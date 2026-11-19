#!/usr/bin/env bash
# Usage: inbox-wait.sh <lead-dir> [who]   (who defaults to lead)
# Run with Bash run_in_background. Exits as soon as <lead-dir>/inbox/<who>.log grows, printing the new lines,
# so its completion notice wakes the session. Unlike a Monitor it has no 30-minute expiry. Start it again after acting.
set -u
d=${1:?lead dir}; who=${2:-lead}; inbox="$d/inbox"; log="$inbox/$who.log"; off="$inbox/.$who.offset"
mkdir -p "$inbox"; touch "$log"
echo $$ > "$inbox/.$who.waiter"
[ -s "$off" ] || wc -c < "$log" | tr -d ' ' > "$off"
while true; do
  size=$(wc -c < "$log" | tr -d ' '); seen=$(cat "$off")
  [ "$size" -lt "$seen" ] && seen=0
  if [ "$size" -gt "$seen" ]; then
    tail -c +"$((seen + 1))" "$log"; echo "$size" > "$off"; exit 0
  fi
  sleep 5
done
