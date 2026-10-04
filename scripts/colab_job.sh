#!/usr/bin/env bash
# Provision a Colab L4 session, run OLMo Phase-2 dry run, download results, always stop.
#
# Auth (human, once): follow COLAB_SKILL.md — e.g.
#   gcloud auth application-default login \
#     --scopes=openid,https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/colaboratory
#   colab --auth=adc whoami
#
# exec timeout: the CLI default is ~30s, so we background the job with nohup
# and poll status.json every 60s via short `colab exec` calls.

set -euo pipefail

SESSION="${SESSION:-rc-olmo-p2}"
REPO_URL="${REPO_URL:-https://github.com/heyronith/constituition.git}"
GIT_SHA="${GIT_SHA:-$(git rev-parse HEAD)}"
VLLM_VERSION="${VLLM_VERSION:-0.30.0}"
LOCAL_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIGS="${CONFIGS:-olmo3_7b_sft olmo3_7b_dpo olmo3_7b_final}"

cleanup() {
  echo "stopping Colab session ${SESSION} (trap)"
  colab stop -s "${SESSION}" || true
}
trap cleanup EXIT

echo "=== colab new L4 session=${SESSION} ==="
colab new --gpu L4 -s "${SESSION}"

echo "=== assert L4 ==="
colab exec -s "${SESSION}" -- nvidia-smi --query-gpu=name --format=csv,noheader | tee /tmp/rc_colab_gpu.txt
grep -qi L4 /tmp/rc_colab_gpu.txt

echo "=== clone + install ==="
# HF_TOKEN is passed via env into the runtime without printing it.
# Pattern from COLAB_SKILL: set remote env, never echo the value.
if [[ -z "${HF_TOKEN:-}" ]]; then
  if [[ -f "${LOCAL_ROOT}/.env" ]]; then
    # shellcheck disable=SC1091
    set -a && source "${LOCAL_ROOT}/.env" && set +a
  fi
fi
if [[ -z "${HF_TOKEN:-}" ]]; then
  echo "HF_TOKEN missing" >&2
  exit 1
fi

colab exec -s "${SESSION}" -- bash -lc "
set -euo pipefail
export HF_TOKEN='${HF_TOKEN}'
cd /content
rm -rf constituition
git clone '${REPO_URL}' constituition
cd constituition
git checkout '${GIT_SHA}'
pip -q install 'vllm==${VLLM_VERSION}' pydantic pyyaml python-dotenv textstat huggingface_hub
pip -q install -e .
mkdir -p /content/rc-runs
"

echo "=== upload runner (already in clone); start background job ==="
# Background + status file because colab exec default timeout is ~30s.
colab exec -s "${SESSION}" -- bash -lc "
set -euo pipefail
export HF_TOKEN='${HF_TOKEN}'
cd /content/constituition
nohup python scripts/colab_run.py \
  --configs ${CONFIGS} \
  --phase 2 \
  --out-root /content/rc-runs \
  --repo-root /content/constituition \
  > /content/rc-runs/job.log 2>&1 &
echo \$! > /content/rc-runs/job.pid
"

echo "=== poll status every 60s ==="
while true; do
  sleep 60
  STATUS="$(colab exec -s "${SESSION}" -- cat /content/rc-runs/status.json 2>/dev/null || echo '{}')"
  echo "status: ${STATUS}"
  STATE="$(python -c "import json,sys; print(json.loads(sys.argv[1] or '{}').get('state',''))" "${STATUS}")"
  if [[ "${STATE}" == "done" ]]; then
    break
  fi
  if [[ "${STATE}" == "error" ]]; then
    colab exec -s "${SESSION}" -- tail -n 80 /content/rc-runs/job.log || true
    exit 1
  fi
done

echo "=== tar + download ==="
colab exec -s "${SESSION}" -- bash -lc "
cd /content && tar -czf rc-runs-phase2.tgz -C /content rc-runs
"
mkdir -p "${LOCAL_ROOT}/runs"
colab download -s "${SESSION}" /content/rc-runs-phase2.tgz "${LOCAL_ROOT}/runs/rc-runs-phase2.tgz"
tar -xzf "${LOCAL_ROOT}/runs/rc-runs-phase2.tgz" -C "${LOCAL_ROOT}/runs" --strip-components=1

echo "=== Colab job finished; trap will stop the session ==="
