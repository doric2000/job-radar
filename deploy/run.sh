#!/usr/bin/env bash
# One scan on the VM (started every 5 minutes by job-radar.timer).
# The `state` branch on GitHub stays the shared copy: a manual workflow run (backlog / alert) writes there,
# so a state commit this machine did not push is adopted before scanning. After the scan the state is
# pushed back when GH_PUSH_TOKEN is set (a fine-grained token: this repository, Contents read/write).
set -euo pipefail
APP="$HOME/job-radar"
DATA="$HOME/job-radar-state"
cd "$APP"
set -a; . "$HOME/.config/job-radar.env"; set +a

git pull -q --ff-only || echo "git pull failed, scanning with the current code"
if ! cmp -s requirements.txt "$DATA/requirements.installed"; then
  .venv/bin/pip install -q -r requirements.txt && cp requirements.txt "$DATA/requirements.installed"
fi

if git fetch -q --depth=1 origin state 2>/dev/null; then
  remote=$(git rev-parse FETCH_HEAD)
  if [ "$remote" != "$(cat "$DATA/synced" 2>/dev/null)" ]; then
    git show FETCH_HEAD:state.json > "$DATA/state.json"
    echo "$remote" > "$DATA/synced"
    echo "adopted state $remote from GitHub"
  fi
fi

.venv/bin/python -m radar.run --state "$DATA/state.json" "$@"

if [ -n "${GH_PUSH_TOKEN:-}" ]; then
  tmp=$(mktemp -d)
  cp "$DATA/state.json" "$tmp/state.json"
  (
    cd "$tmp"
    git init -q -b state
    git -c user.name=job-radar -c user.email=job-radar@users.noreply.github.com add state.json
    git -c user.name=job-radar -c user.email=job-radar@users.noreply.github.com commit -qm "state $(date -u +%FT%TZ)"
    git push -q -f "https://x-access-token:${GH_PUSH_TOKEN}@github.com/doric2000/job-radar.git" state
    git rev-parse HEAD > "$DATA/synced"
  ) || echo "state push failed (kept locally)"
  rm -rf "$tmp"
fi
