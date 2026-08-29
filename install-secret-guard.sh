#!/bin/sh
# Installs the PistonCore secret guard as .git/hooks/pre-commit.
#
# WHY THIS EXISTS: this repo is PUBLIC. The keys live in DEV_BENCH.local.md,
# which is gitignored -- but nothing stops a key being pasted into a file that
# IS tracked. A rule in a doc did not survive contact; a hook does not depend
# on anyone remembering.
#
# The hook is NOT committed (it lives in .git/hooks, which git never clones),
# so it reads its key list from DEV_BENCH.local.md at commit time. That keeps
# the key list out of the public repo. Re-run this script after a fresh clone.
#
# Run:  sh install-secret-guard.sh

set -e
ROOT=$(git rev-parse --show-toplevel)
HOOK="$ROOT/.git/hooks/pre-commit"

cat > "$HOOK" <<'HOOKEOF'
#!/bin/sh
# PistonCore secret guard -- blocks a commit that would publish a key.
# Installed by install-secret-guard.sh. Not tracked by git.
#
# LOCAL IP ADDRESSES ARE NOT SECRETS (Jeremy, 2026-08-28) and are NOT checked.
# RFC1918 addresses are unreachable from outside the house, and a guard that
# cries wolf gets switched off. Keys only.

ROOT=$(git rev-parse --show-toplevel)
BENCH="$ROOT/DEV_BENCH.local.md"
FAIL=0

STAGED=$(git diff --cached --name-only --diff-filter=ACM)
[ -z "$STAGED" ] && exit 0

# 1. A *.local.md file must never be committed, even with `git add -f`.
for F in $STAGED; do
  case "$F" in
    *.local.md)
      echo "BLOCKED: $F is a local-only file and must never be committed."
      FAIL=1
      ;;
  esac
done

# 2. Shape check: long-lived access tokens (JWT). Verified 2026-08-28 to have
#    zero false positives across every tracked file in this repo.
for F in $STAGED; do
  git show ":$F" 2>/dev/null \
    | grep -qE 'eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}' \
    && { echo "BLOCKED: $F contains what looks like a long-lived access token."; FAIL=1; }
done

# 3. Exact check: every key-shaped string in the gitignored bench file.
#    UUIDs are matched EXACTLY, never by shape -- 16 legitimate UUIDs are
#    already tracked (device + config-entry ids), so shape-matching would fire
#    constantly and the guard would get disabled.
if [ -f "$BENCH" ]; then
  NEEDLES=$(grep -ohE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|eyJ[A-Za-z0-9_.-]{40,}' "$BENCH" 2>/dev/null | sort -u)
  if [ -n "$NEEDLES" ]; then
    TMP=$(mktemp)
    printf '%s\n' "$NEEDLES" > "$TMP"
    for F in $STAGED; do
      git show ":$F" 2>/dev/null | grep -qFf "$TMP" \
        && { echo "BLOCKED: $F contains a key from DEV_BENCH.local.md."; FAIL=1; }
    done
    rm -f "$TMP"
  fi
fi

if [ "$FAIL" -ne 0 ]; then
  echo ""
  echo "Nothing was committed."
  echo "Move the key into DEV_BENCH.local.md (gitignored), or remove it."
  echo "The secret itself is never printed here, on purpose."
  echo ""
  echo "Override only if you are certain:  git commit --no-verify"
  exit 1
fi
exit 0
HOOKEOF

chmod +x "$HOOK"
echo "Installed: .git/hooks/pre-commit"
echo "Keys are read from DEV_BENCH.local.md at commit time; none are stored in the repo."
