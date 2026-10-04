#!/usr/bin/env bash
# Provision a Colab L4 session, run OLMo Phase-2B dry run, download results, always stop.
#
# Colab CLI ≥0.6: `colab exec` only runs a Python file (`-f`), not arbitrary shell.
# Helper scripts live in scripts/colab_remote_*.py.
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

cleanup() {
  echo "stopping Colab session ${SESSION} (trap)"
  colab --auth=adc stop -s "${SESSION}" || true
}
trap cleanup EXIT

echo "=== colab new L4 session=${SESSION} ==="
colab --auth=adc new --gpu L4 -s "${SESSION}"

echo "=== assert L4 ==="
colab --auth=adc upload -s "${SESSION}" \
  "${LOCAL_ROOT}/scripts/colab_remote_gpu.py" /content/colab_remote_gpu.py
colab --auth=adc exec -s "${SESSION}" -f /content/colab_remote_gpu.py --timeout 60 \
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

echo "=== upload helpers + setup ==="
for f in colab_remote_setup.py colab_remote_start.py colab_remote_status.py colab_remote_tar.py; do
  colab --auth=adc upload -s "${SESSION}" "${LOCAL_ROOT}/scripts/${f}" "/content/${f}"
done

# Inject env into setup via a tiny wrapper written locally then uploaded.
WRAPPER="$(mktemp)"
cat >"${WRAPPER}" <<EOF
import os
os.environ["HF_TOKEN"] = """${HF_TOKEN}"""
os.environ["RC_REPO_URL"] = """${REPO_URL}"""
os.environ["RC_GIT_SHA"] = """${GIT_SHA}"""
os.environ["RC_VLLM_VERSION"] = """${VLLM_VERSION}"""
os.environ["RC_CONFIGS"] = """${CONFIGS}"""
import runpy
runpy.run_path("/content/colab_remote_setup.py", run_name="__main__")
EOF
colab --auth=adc upload -s "${SESSION}" "${WRAPPER}" /content/_run_setup.py
rm -f "${WRAPPER}"
colab --auth=adc exec -s "${SESSION}" -f /content/_run_setup.py --timeout 1200

echo "=== start background job ==="
START_WRAP="$(mktemp)"
cat >"${START_WRAP}" <<EOF
import os
os.environ["RC_CONFIGS"] = """${CONFIGS}"""
import runpy
runpy.run_path("/content/colab_remote_start.py", run_name="__main__")
EOF
colab --auth=adc upload -s "${SESSION}" "${START_WRAP}" /content/_run_start.py
rm -f "${START_WRAP}"
colab --auth=adc exec -s "${SESSION}" -f /content/_run_start.py --timeout 60

echo "=== poll status every 60s ==="
while true; do
  sleep 60
  STATUS="$(colab --auth=adc exec -s "${SESSION}" -f /content/colab_remote_status.py --timeout 60 2>/dev/null || echo '{}')"
  # Strip CLI noise: keep the JSON object line(s).
  STATUS_JSON="$(printf '%s\n' "${STATUS}" | python -c '
import sys, json
text = sys.stdin.read()
start = text.find("{")
end = text.rfind("}")
print(text[start:end+1] if start >= 0 and end >= start else "{}")
')"
  echo "status: ${STATUS_JSON}"
  STATE="$(python -c "import json,sys; print(json.loads(sys.argv[1] or '{}').get('state',''))" "${STATUS_JSON}")"
  if [[ "${STATE}" == "done" ]]; then
    break
  fi
  if [[ "${STATE}" == "error" ]]; then
    echo "Colab job error; dumping log tail via status payload"
    exit 1
  fi
done

echo "=== tar + download ==="
colab --auth=adc exec -s "${SESSION}" -f /content/colab_remote_tar.py --timeout 120
mkdir -p "${LOCAL_ROOT}/runs"
colab --auth=adc download -s "${SESSION}" /content/rc-runs-phase2b.tgz "${LOCAL_ROOT}/runs/rc-runs-phase2b.tgz"
tar -xzf "${LOCAL_ROOT}/runs/rc-runs-phase2b.tgz" -C "${LOCAL_ROOT}/runs" --strip-components=1

echo "=== Colab job finished; trap will stop the session ==="
