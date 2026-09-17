#!/usr/bin/env bash
# Manage the Neon branches this project uses.
#
#   neon-branch.sh url    <branch> [--pooled]   print a connection string
#   neon-branch.sh create <branch> [parent]     create a branch (default parent: production)
#   neon-branch.sh reset  <branch> [parent]     delete and recreate it from the parent
#   neon-branch.sh delete <branch>              delete a branch
#   neon-branch.sh list                         list branches
#   neon-branch.sh clean  <branch>              drop leftover ledger_test_*/ledger_scratch_* databases
#
# Branches: production (staging/demo data), test (pytest creates its own databases on it).
# Never point TEST_DATABASE_URL at production.
set -euo pipefail

PROJECT_ID="${NEON_PROJECT_ID:-round-violet-29046436}"
DEFAULT_PARENT="${NEON_DEFAULT_PARENT:-production}"
NEON=(neon --project-id "$PROJECT_ID")

usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-1}"; }
[[ $# -ge 1 ]] || usage

command -v neon >/dev/null || { echo "neon CLI not found: npm i -g neon@latest" >&2; exit 127; }

action=$1
shift

case "$action" in
  list)
    "${NEON[@]}" branches list
    ;;
  url)
    [[ $# -ge 1 ]] || usage
    branch=$1; shift
    "${NEON[@]}" connection-string "$branch" "$@"
    ;;
  create)
    [[ $# -ge 1 ]] || usage
    "${NEON[@]}" branches create --name "$1" --parent "${2:-$DEFAULT_PARENT}"
    ;;
  delete)
    [[ $# -ge 1 ]] || usage
    "${NEON[@]}" branches delete "$1"
    ;;
  reset)
    [[ $# -ge 1 ]] || usage
    branch=$1
    parent=${2:-$DEFAULT_PARENT}
    [[ "$branch" != "$parent" ]] || { echo "refusing to reset '$branch' from itself" >&2; exit 2; }
    "${NEON[@]}" branches delete "$branch" || true
    "${NEON[@]}" branches create --name "$branch" --parent "$parent"
    ;;
  clean)
    # Drops databases left behind by interrupted test runs.
    [[ $# -ge 1 ]] || usage
    url=$("${NEON[@]}" connection-string "$1")
    psql "$url" -tAc \
      "SELECT datname FROM pg_database
        WHERE datname LIKE 'ledger_test_%' OR datname LIKE 'ledger_scratch_%'" |
      while read -r db; do
        [[ -n "$db" ]] || continue
        echo "dropping $db"
        psql "$url" -c "DROP DATABASE IF EXISTS \"$db\" WITH (FORCE)" >/dev/null
      done
    ;;
  -h|--help|help)
    usage 0
    ;;
  *)
    echo "unknown action: $action" >&2
    usage
    ;;
esac
