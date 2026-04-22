#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="${SUDO_USER:-$(id -un)}"
ENABLE_SERVICES="true"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-dir)
      APP_DIR="$2"
      shift 2
      ;;
    --app-user)
      APP_USER="$2"
      shift 2
      ;;
    --skip-enable)
      ENABLE_SERVICES="false"
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ ! -f "${APP_DIR}/requirements.txt" ]]; then
  echo "requirements.txt not found under ${APP_DIR}" >&2
  exit 1
fi

if [[ ! -f "${APP_DIR}/.env" ]]; then
  echo ".env not found under ${APP_DIR}. Copy it before installing." >&2
  exit 1
fi

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${APP_DIR}/.venv/bin/python" -m pip install -r "${APP_DIR}/requirements.txt"

render_unit() {
  local template_path="$1"
  local output_path="$2"
  sed \
    -e "s|__APP_DIR__|${APP_DIR}|g" \
    -e "s|__APP_USER__|${APP_USER}|g" \
    "${template_path}" > "${output_path}"
}

render_unit \
  "${APP_DIR}/systemd/mail-telegram-api.service.template" \
  "/etc/systemd/system/mail-telegram-api.service"
render_unit \
  "${APP_DIR}/systemd/mail-telegram-worker.service.template" \
  "/etc/systemd/system/mail-telegram-worker.service"

systemctl daemon-reload

if [[ "${ENABLE_SERVICES}" == "true" ]]; then
  systemctl enable --now mail-telegram-api.service
  systemctl enable --now mail-telegram-worker.service
else
  echo "Services installed but not enabled because --skip-enable was used."
fi

echo "Done."
