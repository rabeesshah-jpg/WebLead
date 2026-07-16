#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

read_env_value() {
  local key="$1"
  local line value

  line="$(grep -E "^${key}=" "${ENV_FILE}" | tail -n 1 || true)"
  if [[ -z "${line}" ]]; then
    return 1
  fi

  value="${line#*=}"
  if [[ "${value}" == \'*\' && "${value}" == *\' ]]; then
    value="${value#\'}"
    value="${value%\'}"
  elif [[ "${value}" == \"*\" && "${value}" == *\" ]]; then
    value="${value#\"}"
    value="${value%\"}"
  fi

  if [[ -z "${value}" ]]; then
    return 1
  fi

  printf '%s' "${value}"
}

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing .env file at ${ENV_FILE}" >&2
  exit 1
fi

if ! SECRET="$(read_env_value "N8N_QUALIFICATION_API_SECRET")"; then
  echo "N8N_QUALIFICATION_API_SECRET is missing or empty in .env" >&2
  exit 1
fi

PAYLOAD='{
  "text": "Thank you. How did you hear about us?",
  "voice": "F1",
  "lang": "en",
  "request_id": "SM_TEST_001"
}'

curl --fail \
  -sS \
  -X POST "http://127.0.0.1:8000/api/internal/qualification/render-audio/" \
  -H "Content-Type: application/json" \
  -H "X-Internal-Webhook-Secret: ${SECRET}" \
  -d "${PAYLOAD}"

echo
