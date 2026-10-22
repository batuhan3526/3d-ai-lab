#!/usr/bin/env bash
# 3D AI Lab — optional model-weight pre-downloader (inventory + gated flags + disk budget).
#
# Workers fetch weights at runtime, but many repos are GATED or NON-COMMERCIAL and
# the total pull is HUNDREDS of GB. This script lets you pre-download only the
# engines you plan to run, into a shared HF cache, with resume support.
#
# Usage:
#   bash infra/scripts/download_models.sh            # list the inventory, do nothing
#   bash infra/scripts/download_models.sh trellis    # download one engine's weights
#   bash infra/scripts/download_models.sh trellis hunyuan triposr
#   bash infra/scripts/download_models.sh all         # everything you have access to
#
# Gated repos require you to (1) accept the license on huggingface.co and
# (2) export HF_TOKEN (or run `huggingface-cli login`) BEFORE downloading.
# Downloads resume automatically (huggingface-cli is idempotent).
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Load HF_TOKEN from .env if present and not already exported.
if [ -z "${HF_TOKEN:-}" ] && [ -f "$REPO_ROOT/.env" ]; then
  HF_TOKEN="$(grep -E '^HF_TOKEN=' "$REPO_ROOT/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' || true)"
fi
export HF_TOKEN="${HF_TOKEN:-}"
export HUGGINGFACE_HUB_TOKEN="${HF_TOKEN}"

# ---------------------------------------------------------------------------
# Inventory. Columns: engine | repo_id | approx size | gated? | license/commercial
# Sizes are rough order-of-magnitude to help you budget disk. Verify on HF.
# ---------------------------------------------------------------------------
INVENTORY=$(cat <<'TSV'
trellis	microsoft/TRELLIS-text-xlarge	~10G	no	MIT / commercial OK
trellis	JeffreyXiang/TRELLIS-image-large	~10G	no	MIT / commercial OK
trellis2	microsoft/TRELLIS.2-4B	~12G	no	MIT / commercial OK (needs GATED DINOv3 at runtime)
hunyuan	tencent/Hunyuan3D-2.1	~30G	accept-terms	Tencent Community / non-commercial-ish (region + 1M MAU limits)
hunyuan	tencent/Hunyuan3D-2mv	~10G	no	Tencent Community / non-commercial-ish
triposr	stabilityai/TripoSR	~1G	no	MIT / commercial OK
sf3d	stabilityai/stable-fast-3d	~2G	GATED	Stability Community / commercial <$1M + register
hi3dgen	Stable-X/trellis-normal-v0-1	~5G	no	MIT / commercial OK
hi3dgen	Stable-X/yoso-normal-v1-8-1	~1G	no	MIT / commercial OK
partcrafter	wgsxm/PartCrafter	~5G	no	MIT (code); weights license unconfirmed
partcrafter	briaai/RMBG-1.4	~0.2G	accept-terms	NON-COMMERCIAL (matting)
flux	black-forest-labs/FLUX.1-dev	~24G	GATED	FLUX.1 [dev] NON-COMMERCIAL
flux	ZhengPeng7/BiRefNet	~1G	no	MIT (per upstream) / matting
meshflow	facebook/meshflow	~5G	GATED	FAIR NC (Meta) NON-COMMERCIAL
meshflow	facebook/dinov3-vitl16-pretrain-lvd1689m	~1G	GATED	DINOv3 License (Meta) — also used by trellis2
worldtracing	haoz19/object-model-6layer	~5G	GATED	CC BY-NC-ND (non-commercial, no-derivatives)
sam3d	SAM3D-Objects (Meta, acceptance-gated HF)	~20G	GATED	SAM License (Meta) — commercial OK w/ conditions
videomdm	AmirMann/VideoMDM	~2G	no	MIT code; SMPL/SMPL-X deps GATED + non-commercial
TSV
)

print_inventory() {
  printf '\n\033[1mModel weight inventory\033[0m  (sizes approximate — verify on HF)\n\n'
  printf '  %-13s %-45s %-7s %-13s %s\n' ENGINE REPO_ID SIZE GATED LICENSE
  printf '  %-13s %-45s %-7s %-13s %s\n' ------ ------- ---- ----- -------
  while IFS=$'\t' read -r engine repo size gated lic; do
    [ -z "$engine" ] && continue
    printf '  %-13s %-45s %-7s %-13s %s\n' "$engine" "$repo" "$size" "$gated" "$lic"
  done <<< "$INVENTORY"
  cat <<'EOF'

GATED repos: accept the license on huggingface.co, then export HF_TOKEN
  (or run `huggingface-cli login`) before downloading.
SMPL/SMPL-X for VideoMDM full animation must be fetched from the MPI site
  (smpl-x.is.tue.mpg.de) — NOT via this script.
Total for "all" is several hundred GB — download only what you will run.

EOF
}

download_one() {
  local repo="$1" gated="$3"
  if [ "$gated" = "GATED" ] && [ -z "$HF_TOKEN" ]; then
    printf '\033[1;33m   SKIP %s — gated, no HF_TOKEN set\033[0m\n' "$repo"
    return 0
  fi
  # Some "repos" in the inventory are manual (SAM3D) — skip auto-download.
  case "$repo" in
    *" "* ) printf '   MANUAL %s — download per its own instructions\n' "$repo"; return 0;;
  esac
  printf '\033[1;36m   downloading %s\033[0m\n' "$repo"
  huggingface-cli download "$repo" ${HF_TOKEN:+--token "$HF_TOKEN"} || \
    printf '\033[1;31m   FAILED %s (access? disk? token?)\033[0m\n' "$repo"
}

# --- main -------------------------------------------------------------------
if [ "$#" -eq 0 ]; then
  print_inventory
  echo "Pass one or more engine names (or 'all') to download. e.g.:"
  echo "  bash infra/scripts/download_models.sh trellis triposr"
  exit 0
fi

want=" $* "


# HF motorları istendi mi? (motor adı ya da 'all')
_need_hf=0
if [[ "$want" == *" all "* ]]; then
  _need_hf=1
else
  while IFS=$'\t' read -r engine _repo _size _gated _lic; do
    [ -z "$engine" ] && continue
    [[ "$want" == *" $engine "* ]] && _need_hf=1
  done <<< "$INVENTORY"
fi

if [ "$_need_hf" -eq 1 ]; then
  # huggingface-cli from PATH, else a throwaway one via uvx (no global install).
  if ! command -v huggingface-cli >/dev/null 2>&1; then
    huggingface-cli() { uvx --from "huggingface_hub[cli]<1" huggingface-cli "$@"; }
  fi
  while IFS=$'\t' read -r engine repo size gated lic; do
    [ -z "$engine" ] && continue
    if [[ "$want" == *" all "* ]] || [[ "$want" == *" $engine "* ]]; then
      download_one "$repo" "$size" "$gated"
    fi
  done <<< "$INVENTORY"
  echo "Done. Weights cached under \${HF_HOME:-~/.cache/huggingface}."
fi
