#!/bin/sh
set -eu

WHISPER_ROOT="${KCXDOC_WHISPER_ROOT:-/opt/kcxdocumentor/external/whisper}"
WHISPER_BIN_DIR="${WHISPER_ROOT}/bin"
WHISPER_MODEL_DIR="${WHISPER_ROOT}/models"
WHISPER_VERSION_FILE="${WHISPER_ROOT}/.whispercpp-version"
WHISPER_API_URL="${KCXDOC_WHISPER_RELEASE_API_URL:-https://api.github.com/repos/ggml-org/whisper.cpp/releases/latest}"
WHISPER_MODEL_NAME="${KCXDOC_WHISPER_MODEL_NAME:-ggml-base.en.bin}"
WHISPER_MODEL_URL="${KCXDOC_WHISPER_MODEL_URL:-https://huggingface.co/ggerganov/whisper.cpp/resolve/main/${WHISPER_MODEL_NAME}}"

bootstrap_whisper() {
  if [ "${KCXDOC_BOOTSTRAP_WHISPER:-true}" != "true" ]; then
    return 0
  fi

  mkdir -p "${WHISPER_BIN_DIR}" "${WHISPER_MODEL_DIR}"

  latest_json="$(mktemp)"
  curl -fsSL "${WHISPER_API_URL}" -o "${latest_json}"
  latest_tag="$(python - "${latest_json}" <<'PY'
import json
import sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(payload.get("tag_name", ""))
PY
)"
  tarball_url="$(python - "${latest_json}" <<'PY'
import json
import sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(payload.get("tarball_url", ""))
PY
)"
  rm -f "${latest_json}"

  if [ -z "${latest_tag}" ] || [ -z "${tarball_url}" ]; then
    echo "Could not resolve latest whisper.cpp release metadata." >&2
    exit 1
  fi

  current_tag=""
  if [ -f "${WHISPER_VERSION_FILE}" ]; then
    current_tag="$(cat "${WHISPER_VERSION_FILE}")"
  fi

  if [ "${KCXDOC_WHISPER_UPDATE:-latest}" = "never" ] \
    && [ -x "${KCXDOC_WHISPER_CLI:-${WHISPER_BIN_DIR}/whisper-cli}" ]; then
    ensure_whisper_model
    return 0
  fi

  if [ "${current_tag}" != "${latest_tag}" ] \
    || [ ! -x "${KCXDOC_WHISPER_CLI:-${WHISPER_BIN_DIR}/whisper-cli}" ]; then
    build_whisper_cpp "${latest_tag}" "${tarball_url}"
  fi

  ensure_whisper_model
}

build_whisper_cpp() {
  latest_tag="$1"
  tarball_url="$2"
  build_root="$(mktemp -d)"
  source_tar="${build_root}/whisper.cpp.tar.gz"
  source_dir="${build_root}/src"
  build_dir="${build_root}/build"

  echo "Bootstrapping whisper.cpp ${latest_tag} into ${WHISPER_ROOT}..."
  curl -fsSL "${tarball_url}" -o "${source_tar}"
  mkdir -p "${source_dir}" "${build_dir}"
  tar -xzf "${source_tar}" -C "${source_dir}" --strip-components=1

  cmake -S "${source_dir}" -B "${build_dir}" -DCMAKE_BUILD_TYPE=Release -DWHISPER_BUILD_TESTS=OFF
  cmake --build "${build_dir}" --config Release --target whisper-cli -j "$(nproc)"

  candidate="$(find "${build_dir}" -type f -name whisper-cli | head -n 1)"
  if [ -z "${candidate}" ]; then
    echo "whisper-cli was not produced by the whisper.cpp build." >&2
    exit 1
  fi

  cp "${candidate}" "${WHISPER_BIN_DIR}/whisper-cli"
  chmod +x "${WHISPER_BIN_DIR}/whisper-cli"

  find "${build_dir}" -type f \( -name 'libwhisper*.so*' -o -name 'libggml*.so*' \) -exec cp {} "${WHISPER_BIN_DIR}/" \; || true
  printf "%s" "${latest_tag}" > "${WHISPER_VERSION_FILE}"
  rm -rf "${build_root}"
}

ensure_whisper_model() {
  model_path="${KCXDOC_WHISPER_MODEL:-${WHISPER_MODEL_DIR}/${WHISPER_MODEL_NAME}}"
  if [ -f "${model_path}" ]; then
    return 0
  fi
  mkdir -p "$(dirname "${model_path}")"
  echo "Downloading Whisper model to ${model_path}..."
  curl -fL "${WHISPER_MODEL_URL}" -o "${model_path}"
}

bootstrap_whisper

exec "$@"
