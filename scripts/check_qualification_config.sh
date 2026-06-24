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

if [[ -f "${ENV_FILE}" ]]; then
  echo ".env exists: yes"
else
  echo ".env exists: no"
  exit 1
fi

if ENV_SECRET="$(read_env_value "N8N_QUALIFICATION_API_SECRET")"; then
  echo "N8N_QUALIFICATION_API_SECRET present in .env: yes"
  ENV_SECRET_LENGTH="${#ENV_SECRET}"
else
  echo "N8N_QUALIFICATION_API_SECRET present in .env: no"
  ENV_SECRET_LENGTH=0
fi

PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python"
fi

DJANGO_SECRET_LENGTH="$(
  cd "${ROOT_DIR}" && \
  "${PYTHON_BIN}" -c "import os, django; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); django.setup(); from django.conf import settings; print(len(settings.N8N_QUALIFICATION_API_SECRET or ''))"
)"

echo "Django N8N_QUALIFICATION_API_SECRET length: ${DJANGO_SECRET_LENGTH}"
echo "Extracted .env N8N_QUALIFICATION_API_SECRET length: ${ENV_SECRET_LENGTH}"

if [[ "${DJANGO_SECRET_LENGTH}" -eq "${ENV_SECRET_LENGTH}" && "${DJANGO_SECRET_LENGTH}" -gt 0 ]]; then
  echo "Secret lengths match: yes"
else
  echo "Secret lengths match: no"
  exit 1
fi
