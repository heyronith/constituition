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
# Kernel can briefly drop the websocket right after READY; wait then retry.
sleep 15

echo "=== assert L4 ==="
GPU_OK=0
for attempt in 1 2 3 4 5; do
  if colab --auth=adc exec -s "${SESSION}" -f "${SCRIPTS}/colab_remote_gpu.py" --timeout 120 \
    | tee /tmp/rc_colab_gpu.txt; then
    if grep -qi L4 /tmp/rc_colab_gpu.txt; then
      GPU_OK=1
      break
    fi
  fi
  echo "GPU assert attempt ${attempt} failed; sleeping 20s"
  sleep 20
done
if [[ "${GPU_OK}" -ne 1 ]]; then
  echo "Colab GPU assert failed after retries" >&2
  exit 1
fi

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
  sed '/^if __name__/,$d' "${SCRIPTS}/colab_remote_setup.py"
  printf '\nmain()\n'
} >"${WRAPPER}"
SETUP_OUT="$(mktemp -t rc_colab_setup_out.XXXXXX)"
set +e
colab --auth=adc exec -s "${SESSION}" -f "${WRAPPER}" --timeout 1200 | tee "${SETUP_OUT}"
SETUP_RC=${PIPESTATUS[0]}
set -e
rm -f "${WRAPPER}"
if [[ ${SETUP_RC} -ne 0 ]] || ! grep -q SETUP_OK "${SETUP_OUT}"; then
  echo "Colab setup failed" >&2
  rm -f "${SETUP_OUT}"
  exit 1
fi
rm -f "${SETUP_OUT}"

# Resume: upload any local partial run dirs for this job's configs.
CHECKPOINT_TGZ="${LOCAL_ROOT}/runs/${TAR_NAME%.tgz}-checkpoint.tgz"
if [[ -n "${RC_RUN_TAG}" ]]; then
  NEED_RESUME=0
  for cfg in ${CONFIGS}; do
    if [[ -d "${LOCAL_ROOT}/runs/${RC_RUN_TAG}/${cfg}" ]]; then
      NEED_RESUME=1
      break
    fi
  done
  if [[ "${NEED_RESUME}" -eq 1 ]]; then
    echo "=== upload resume checkpoint for ${RC_RUN_TAG} (${CONFIGS}) ==="
    RESUME_TGZ="$(mktemp -t rc_resume.XXXXXX.tgz)"
    (
      cd "${LOCAL_ROOT}/runs"
      paths=()
      for cfg in ${CONFIGS}; do
        if [[ -d "${RC_RUN_TAG}/${cfg}" ]]; then
          paths+=("${RC_RUN_TAG}/${cfg}")
        fi
      done
      # also carry manifest if present
      if [[ -f "${RC_RUN_TAG}/manifest.json" ]]; then
        paths+=("${RC_RUN_TAG}/manifest.json")
      fi
      tar -czf "${RESUME_TGZ}" "${paths[@]}"
    )
    colab --auth=adc upload -s "${SESSION}" "${RESUME_TGZ}" "/content/rc-resume.tgz"
    RESUME_WRAPPER="$(mktemp -t rc_colab_resume.XXXXXX.py)"
    cat >"${RESUME_WRAPPER}" <<'EOF'
import subprocess
from pathlib import Path
subprocess.check_call(["tar", "-xzf", "/content/rc-resume.tgz", "-C", "/content/rc-runs"])
print("RESUME_OK", flush=True)
for p in sorted(Path("/content/rc-runs").rglob("rounds.jsonl"))[:5]:
    print("resume_sample", p)
EOF
    colab --auth=adc exec -s "${SESSION}" -f "${RESUME_WRAPPER}" --timeout 300
    rm -f "${RESUME_WRAPPER}" "${RESUME_TGZ}"
  fi
fi

echo "=== start job ==="
START_WRAPPER="$(mktemp -t rc_colab_start.XXXXXX.py)"
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
  sed '/^if __name__/,$d' "${SCRIPTS}/colab_remote_setup.py"
  printf '\nstart_job()\n'
} >"${START_WRAPPER}"
START_OUT="$(mktemp -t rc_colab_start_out.XXXXXX)"
set +e
colab --auth=adc exec -s "${SESSION}" -f "${START_WRAPPER}" --timeout 300 | tee "${START_OUT}"
START_RC=${PIPESTATUS[0]}
set -e
rm -f "${START_WRAPPER}"
if [[ ${START_RC} -ne 0 ]] || ! grep -q STARTED "${START_OUT}"; then
  echo "Colab start_job failed" >&2
  rm -f "${START_OUT}"
  exit 1
fi
rm -f "${START_OUT}"

checkpoint_pull() {
  local label="$1"
  echo "=== checkpoint pull (${label}) ==="
  TAR_WRAPPER="$(mktemp -t rc_colab_tar.XXXXXX.py)"
  cat >"${TAR_WRAPPER}" <<EOF
import subprocess
TAR_NAME = """${TAR_NAME}"""
subprocess.check_call(["tar", "-czf", f"/content/{TAR_NAME}", "-C", "/content", "rc-runs"])
print(f"TAR_OK {TAR_NAME}")
EOF
  if colab --auth=adc exec -s "${SESSION}" -f "${TAR_WRAPPER}" --timeout 180; then
    mkdir -p "${LOCAL_ROOT}/runs"
    if colab --auth=adc download -s "${SESSION}" "/content/${TAR_NAME}" "${LOCAL_ROOT}/runs/${TAR_NAME}"; then
      tar -xzf "${LOCAL_ROOT}/runs/${TAR_NAME}" -C "${LOCAL_ROOT}/runs" --strip-components=1
      cp -f "${LOCAL_ROOT}/runs/${TAR_NAME}" "${CHECKPOINT_TGZ}"
      echo "CHECKPOINT_OK ${label}"
    fi
  fi
  rm -f "${TAR_WRAPPER}"
}

echo "=== poll status every 90s (checkpoint every 4 polls) ==="
POLL_I=0
EMPTY_STREAK=0
while true; do
  sleep 90
  POLL_I=$((POLL_I + 1))
  # Redirect stderr so connection blips don't look like fatal failures.
  STATUS="$(colab --auth=adc exec -s "${SESSION}" -f "${SCRIPTS}/colab_remote_status.py" --timeout 90 2>/dev/null || true)"
  STATUS_JSON="$(printf '%s\n' "${STATUS}" | python3 -c '
import sys
text = sys.stdin.read()
start = text.find("{")
end = text.rfind("}")
print(text[start:end+1] if start >= 0 and end >= start else "{}")
' 2>/dev/null || echo '{}')"
  echo "status: ${STATUS_JSON}"
  STATE="$(python3 -c "import json,sys; print(json.loads(sys.argv[1] or '{}').get('state',''))" "${STATUS_JSON}" 2>/dev/null || true)"
  if [[ -z "${STATE}" ]]; then
    EMPTY_STREAK=$((EMPTY_STREAK + 1))
  else
    EMPTY_STREAK=0
  fi
  if [[ "${STATE}" == "done" ]]; then
    break
  fi
  if [[ "${STATE}" == "error" ]]; then
    echo "Colab job error"
    break
  fi
  # Periodic checkpoint so a session drop does not lose all progress.
  if (( POLL_I % 4 == 0 )); then
    checkpoint_pull "poll_${POLL_I}" || true
  fi
  # Session likely dead after several empty status reads.
  if (( EMPTY_STREAK >= 3 )); then
    echo "Colab session appears dead (empty status ×${EMPTY_STREAK}); pulling last checkpoint"
    checkpoint_pull "session_dead" || true
    exit 2
  fi
done

echo "=== tar + download ==="
checkpoint_pull "final" || {
  echo "final checkpoint failed" >&2
  exit 1
}

echo "=== Colab job finished; trap will stop the session ==="
