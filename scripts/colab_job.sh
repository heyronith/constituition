#!/usr/bin/env bash
# Provision a Colab L4 session, run OLMo Phase-2B dry run, download results, always stop.
#
# Colab CLI: `colab exec -f PATH` reads a *local* Python file and runs it in the
# remote kernel (it does not open a remote path).
#
# Auth (human, once):
#   gcloud auth application-default login \
#     --scopes=openid,https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/colaboratory
#   colab --auth=adc whoami

set -euo pipefail

SESSION="${SESSION:-rc-olmo-p2b}"
REPO_URL="${REPO_URL:-https://github.com/heyronith/constituition.git}"
GIT_SHA="${GIT_SHA:-$(git rev-parse HEAD)}"
VLLM_VERSION="${VLLM_VERSION:-0.30.0}"
LOCAL_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIGS="${CONFIGS:-olmo3_7b_sft olmo3_7b_dpo olmo3_7b_final}"
SCRIPTS="${LOCAL_ROOT}/scripts"

cleanup() {
  echo "stopping Colab session ${SESSION} (trap)"
  colab --auth=adc stop -s "${SESSION}" || true
}
trap cleanup EXIT

echo "=== colab new L4 session=${SESSION} ==="
colab --auth=adc new --gpu L4 -s "${SESSION}"

echo "=== assert L4 ==="
colab --auth=adc exec -s "${SESSION}" -f "${SCRIPTS}/colab_remote_gpu.py" --timeout 60 \
  | tee /tmp/rc_colab_gpu.txt
grep -qi L4 /tmp/rc_colab_gpu.txt

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

echo "=== clone + install ==="
WRAPPER="$(mktemp -t rc_colab_setup.XXXXXX.py)"
{
  cat <<EOF
import os
os.environ["HF_TOKEN"] = """${HF_TOKEN}"""
os.environ["RC_REPO_URL"] = """${REPO_URL}"""
os.environ["RC_GIT_SHA"] = """${GIT_SHA}"""
os.environ["RC_VLLM_VERSION"] = """${VLLM_VERSION}"""
EOF
  # Body without the module's __main__ guard.
  sed '/^if __name__/,$d' "${SCRIPTS}/colab_remote_setup.py"
  printf '\nmain()\n'
} >"${WRAPPER}"
colab --auth=adc exec -s "${SESSION}" -f "${WRAPPER}" --timeout 1200
rm -f "${WRAPPER}"

echo "=== start background job ==="
START_WRAP="$(mktemp -t rc_colab_start.XXXXXX.py)"
{
  cat <<EOF
import os
os.environ["RC_CONFIGS"] = """${CONFIGS}"""
EOF
  sed '/^if __name__/,$d' "${SCRIPTS}/colab_remote_start.py"
  printf '\nmain()\n'
} >"${START_WRAP}"
colab --auth=adc exec -s "${SESSION}" -f "${START_WRAP}" --timeout 60
rm -f "${START_WRAP}"

echo "=== poll status every 60s ==="
while true; do
  sleep 60
  STATUS="$(colab --auth=adc exec -s "${SESSION}" -f "${SCRIPTS}/colab_remote_status.py" --timeout 60 2>/dev/null || echo '{}')"
  STATUS_JSON="$(printf '%s\n' "${STATUS}" | python3 -c '
import sys
text = sys.stdin.read()
start = text.find("{")
end = text.rfind("}")
print(text[start:end+1] if start >= 0 and end >= start else "{}")
')"
  echo "status: ${STATUS_JSON}"
  STATE="$(python3 -c "import json,sys; print(json.loads(sys.argv[1] or '{}').get('state',''))" "${STATUS_JSON}")"
  if [[ "${STATE}" == "done" ]]; then
    break
  fi
  if [[ "${STATE}" == "error" ]]; then
    echo "Colab job error"
    exit 1
  fi
done

echo "=== tar + download ==="
colab --auth=adc exec -s "${SESSION}" -f "${SCRIPTS}/colab_remote_tar.py" --timeout 120
mkdir -p "${LOCAL_ROOT}/runs"
colab --auth=adc download -s "${SESSION}" /content/rc-runs-phase2b.tgz "${LOCAL_ROOT}/runs/rc-runs-phase2b.tgz"
tar -xzf "${LOCAL_ROOT}/runs/rc-runs-phase2b.tgz" -C "${LOCAL_ROOT}/runs" --strip-components=1

echo "=== Colab job finished; trap will stop the session ==="
