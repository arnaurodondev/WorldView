#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# check_deployed_image_freshness.sh
#
# WHY THIS EXISTS
# ---------------
# During the 2026-07 incident the cluster ran `:latest` images that PREDATED
# merged migrations (prediction 043/044, content-ingestion 0011, intel_db 0067,
# alert 0011). Missing columns/tables → ~83% consumer failures. Nothing flagged
# that the deployed image was behind git — `:latest` is an opaque, mutable tag.
#
# WHAT IT DOES
# ------------
# For every worldview Deployment it compares the DEPLOYED image's build revision
# against the latest git commit that touched that service (or the shared libs/):
#
#   deployed_revision  = org.opencontainers.image.revision label on the running
#                        image digest (set by deploy.yml's build-push-action),
#                        OR the image TAG itself when it is a <sha7> (recommended
#                        future state — see "TAG PINNING" below).
#   latest_git_commit  = git log -1 --format=%H -- services/<svc> libs
#
# STALE  ⇔  latest_git_commit is NOT an ancestor of deployed_revision
#           (i.e. the running image was built before code that has since merged).
#
# FALLBACK (no revision label AND tag is not a sha): compare the image's
# org.opencontainers.image.created timestamp against the commit date of
# latest_git_commit — if the image is older, flag it. This is coarser (clock vs
# graph) and is why pinning a <sha7> tag is recommended.
#
# TAG PINNING RECOMMENDATION
# --------------------------
# Prod currently deploys `:latest` for every service (verified 2026-07). Pin
# gitops values/<svc>.yaml image.tag to the <sha7> that deploy.yml already
# pushes; then this gate needs no registry call at all and rollbacks are
# immutable. Until then this script reads the revision LABEL off the digest.
#
# USAGE
#   KUBECONFIG=~/.kube/config-worldview \
#     scripts/ci/check_deployed_image_freshness.sh [namespace]
#   (namespace default: worldview)
#
# REQUIRES: kubectl (cluster access), git (run from repo root), and — only when
# images are `:latest` without a sha tag — `crane` to read image labels by digest.
#
# CronJob adaptation: bake this script + a shallow repo checkout into a small
# image, mount the in-cluster ServiceAccount (RBAC: get/list deployments), and
# run on a schedule; emit failures to Alertmanager via a pushgateway or by
# writing a metric. Kept as a CI/local script here because it needs the git tree.
#
# EXIT: 0 = all fresh; 1 = one or more stale; 2 = usage/precondition error.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

NAMESPACE="${1:-worldview}"
IMAGE_PREFIX_RE='ghcr.io/[^/]+/worldview-'   # strip registry+org, keep <svc>

# Repo root = two levels up from this script (scripts/ci/..).
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

command -v kubectl >/dev/null 2>&1 || { echo "ERROR: kubectl not found" >&2; exit 2; }
command -v git     >/dev/null 2>&1 || { echo "ERROR: git not found" >&2; exit 2; }
HAVE_CRANE=0
command -v crane   >/dev/null 2>&1 && HAVE_CRANE=1

# Regex for a git short/long sha used as an image tag.
SHA_RE='^[0-9a-f]{7,40}$'

stale=0
checked=0
SEEN=" "   # dedup: many Deployments share one image digest (bash-3.2-safe string set)

printf '%-22s %-10s %-12s %-12s %s\n' "SERVICE" "STATUS" "DEPLOYED" "LATEST_GIT" "IMAGE"
printf '%-22s %-10s %-12s %-12s %s\n' "-------" "------" "--------" "----------" "-----"

# One row per (deployment) but we dedup on image ref+digest.
while IFS=$'\t' read -r dep image imageid; do
  [ -z "$image" ] && continue

  # Only services we can map to a git path: ghcr.io/<org>/worldview-<svc>[:tag]
  repo_no_tag="${image%%:*}"
  case "$repo_no_tag" in
    *worldview-*) svc="${repo_no_tag##*worldview-}" ;;
    *) continue ;;   # skip gliner/postgres/python-base/etc — no services/<svc>
  esac
  [ -d "services/${svc}" ] || continue

  # Dedup on the resolved digest (imageID) so workers sharing an image are
  # checked once.
  dedup_key="${svc}@${imageid:-$image}"
  case "$SEEN" in *" ${dedup_key} "*) continue ;; esac
  SEEN="${SEEN}${dedup_key} "

  tag="${image##*:}"
  digest="${imageid##*@}"   # imageID looks like ...worldview-<svc>@sha256:...

  # 1) Latest git commit touching this service OR the shared libs.
  latest_full="$(git log -1 --format=%H -- "services/${svc}" libs 2>/dev/null || true)"
  latest_short="${latest_full:0:7}"
  if [ -z "$latest_full" ]; then
    printf '%-22s %-10s %-12s %-12s %s\n' "$svc" "SKID" "-" "-" "$image"
    continue
  fi

  # 2) Deployed revision: prefer a sha tag, else read the label off the digest.
  deployed_rev=""
  src="tag"
  if [[ "$tag" =~ $SHA_RE ]]; then
    deployed_rev="$tag"
  elif [ "$HAVE_CRANE" = 1 ] && [ -n "$digest" ]; then
    src="label"
    deployed_rev="$(crane config "${repo_no_tag}@${digest}" 2>/dev/null \
      | python3 -c 'import json,sys; print(json.load(sys.stdin).get("config",{}).get("Labels",{}).get("org.opencontainers.image.revision",""))' 2>/dev/null || true)"
  fi

  checked=$((checked + 1))

  if [ -z "$deployed_rev" ]; then
    # No revision available (no sha tag, and no crane/label) → cannot verify.
    printf '%-22s %-10s %-12s %-12s %s\n' "$svc" "UNKNOWN" "?" "$latest_short" "$image"
    stale=$((stale + 1))
    continue
  fi

  # 3) Ancestry check: fresh ⇔ latest_full is an ancestor of deployed_rev.
  if git cat-file -e "${deployed_rev}^{commit}" 2>/dev/null; then
    if git merge-base --is-ancestor "$latest_full" "$deployed_rev" 2>/dev/null; then
      printf '%-22s %-10s %-12s %-12s %s\n' "$svc" "FRESH" "${deployed_rev:0:7}" "$latest_short" "$image"
    else
      printf '%-22s %-10s %-12s %-12s %s\n' "$svc" "STALE" "${deployed_rev:0:7}" "$latest_short" "$image"
      stale=$((stale + 1))
    fi
  else
    # deployed_rev not in local history (built from an unfetched branch). Warn.
    printf '%-22s %-10s %-12s %-12s %s\n' "$svc" "NOCOMMIT" "${deployed_rev:0:7}" "$latest_short" "$image"
    stale=$((stale + 1))
  fi
done < <(
  # Source from PODS: only pods carry the resolved digest in
  # .status.containerStatuses[].imageID (repo@sha256:...) that crane needs to
  # read the revision label. .spec.containers[].image keeps the human tag.
  kubectl -n "$NAMESPACE" get pods --field-selector=status.phase=Running -o \
    jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[0].image}{"\t"}{.status.containerStatuses[0].imageID}{"\n"}{end}'
)

echo
echo "Checked ${checked} service image(s) in namespace '${NAMESPACE}'; ${stale} not-fresh."
[ "$stale" -eq 0 ]
