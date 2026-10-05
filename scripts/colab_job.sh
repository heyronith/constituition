#!/usr/bin/env bash
# Provision a Colab L4 session, run OLMo jobs, download results, always stop.
#
# Colab CLI: `colab exec -f PATH` reads a *local* Python file and runs it in the
# remote kernel (it does not open a remote path).
#
# Env overrides:
#   SESSION, CONFIGS, RC_MODE (dryrun|olmo_check|pilot), RC_PHASE, RC_RUN_TAG
#
# Auth (human, once):
#   gcloud auth application-default login \
#     --scopes=openid,https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/colaboratory
#   colab --auth=adc whoami

set -euo pipefail

SESSION="${SESSION:-rc-olmo-p3}"
REPO_URL="${REPO_URL:-https://github.com/heyronith/constituition.git}"
GIT_SHA="${GIT_SHA:-$(git rev-parse HEAD)}"
VLLM_VERSION="${VLLM_VERSION:-0.30.0}"
LOCAL_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIGS="${CONFIGS:-olmo3_7b_sft olmo3_7b_dpo olmo3_7b_final}"
RC_MODE="${RC_MODE:-olmo_check}"
RC_PHASE="${RC_PHASE:-3}"
RC_RUN_TAG="${RC_RUN_TAG:-}"
SCRIPTS="${LOCAL_ROOT}/scripts"
TAR_NAME="${TAR_NAME:-rc-runs-${RC_MODE}.tgz}"

cleanup() {
  echo "stopping Colab session ${SESSION} (trap)"
  colab --auth=adc stop -s "${SESSION}" || true
}
trap cleanup EXIT

echo "=== colab new L4 session=${SESSION} mode=${RC_MODE} ==="
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
os.environ["RC_CONFIGS"] = """${CONFIGS}"""
os.environ["RC_MODE"] = """${RC_MODE}"""
os.environ["RC_PHASE"] = """${RC_PHASE}"""
os.environ["RC_RUN_TAG"] = """${RC_RUN_TAG}"""
EOF
  # Body without the module's __main__ guard; start job in the same exec.
  sed '/^if __name__/,$d' "${SCRIPTS}/colab_remote_setup.py"
  printf '\nmain()\nstart_job()\n'
} >"${WRAPPER}"
SETUP_OUT="$(mktemp -t rc_colab_setup_out.XXXXXX)"
set +e
colab --auth=adc exec -s "${SESSION}" -f "${WRAPPER}" --timeout 1200 | tee "${SETUP_OUT}"
SETUP_RC=${PIPESTATUS[0]}
set -e
rm -f "${WRAPPER}"
if [[ ${SETUP_RC} -ne 0 ]] || ! grep -q SETUP_OK "${SETUP_OUT}" || ! grep -q STARTED "${SETUP_OUT}"; then
  echo "Colab setup/start failed" >&2
  rm -f "${SETUP_OUT}"
  exit 1
fi
rm -f "${SETUP_OUT}"

echo "=== poll status every 60s ==="
while true; do
  sleep 60
  STATUS="$(colab --auth=adc exec -s "${SESSION}" -f "${SCRIPTS}/colab_remote_status.py" --timeout 60 || true)"
  STATUS_JSON="$(printf '%s\n' "${STATUS}" | python3 -c '
import sys
text = sys.stdin.read()
start = text.find("{")
end = text.rfind("}")
print(text[start:end+1] if start >= 0 and end >= start else "{}")
' 2>/dev/null || echo '{}')"
  echo "status: ${STATUS_JSON}"
  STATE="$(python3 -c "import json,sys; print(json.loads(sys.argv[1] or '{}').get('state',''))" "${STATUS_JSON}" 2>/dev/null || true)"
  if [[ "${STATE}" == "done" ]]; then
    break
  fi
  if [[ "${STATE}" == "error" ]]; then
    echo "Colab job error"
    # Still try to fetch logs/tarball for diagnosis.
    break
  fi
done

echo "=== tar + download ==="
TAR_WRAPPER="$(mktemp -t rc_colab_tar.XXXXXX.py)"
cat >"${TAR_WRAPPER}" <<EOF
import os
import subprocess
TAR_NAME = """${TAR_NAME}"""
subprocess.check_call(["tar", "-czf", f"/content/{TAR_NAME}", "-C", "/content", "rc-runs"])
print(f"TAR_OK {TAR_NAME}")
EOF
colab --auth=adc exec -s "${SESSION}" -f "${TAR_WRAPPER}" --timeout 120
rm -f "${TAR_WRAPPER}"
mkdir -p "${LOCAL_ROOT}/runs"
colab --auth=adc download -s "${SESSION}" "/content/${TAR_NAME}" "${LOCAL_ROOT}/runs/${TAR_NAME}"
tar -xzf "${LOCAL_ROOT}/runs/${TAR_NAME}" -C "${LOCAL_ROOT}/runs" --strip-components=1

echo "=== Colab job finished; trap will stop the session ==="
