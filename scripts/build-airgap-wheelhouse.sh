#!/usr/bin/env bash
set -euo pipefail

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
wheelhouse_dir="${repository_root}/dist/wheelhouse"
requirements_file="${repository_root}/reference_labs/white_goods/runtime/wheelhouse-requirements.txt"
target_platform="${HARNESS_WHEEL_PLATFORM:-manylinux_2_17_x86_64}"
target_python="${HARNESS_WHEEL_PYTHON_VERSION:-311}"

mkdir -p "${wheelhouse_dir}"
find "${wheelhouse_dir}" -maxdepth 1 -type f \( -name '*.whl' -o -name 'wheelhouse-manifest.json' \) -delete
python -m pip download \
  --dest "${wheelhouse_dir}" \
  --only-binary=:all: \
  --platform "${target_platform}" \
  --implementation cp \
  --python-version "${target_python}" \
  -r "${requirements_file}"

WHEELHOUSE_DIR="${wheelhouse_dir}" \
WHEELHOUSE_REQUIREMENTS="${requirements_file}" \
WHEELHOUSE_PLATFORM="${target_platform}" \
WHEELHOUSE_PYTHON="${target_python}" \
python - <<'PY'
import hashlib
import json
import os
from pathlib import Path

root = Path(os.environ["WHEELHOUSE_DIR"])
requirements = Path(os.environ["WHEELHOUSE_REQUIREMENTS"])
files = {
    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(root.glob("*.whl"))
}
manifest = {
    "schemaVersion": "data.harness.wheelhouse/v1",
    "target": {
        "platform": os.environ["WHEELHOUSE_PLATFORM"],
        "implementation": "cp",
        "pythonVersion": os.environ["WHEELHOUSE_PYTHON"],
    },
    "requirementsSha256": hashlib.sha256(requirements.read_bytes()).hexdigest(),
    "files": files,
}
(root / "wheelhouse-manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
