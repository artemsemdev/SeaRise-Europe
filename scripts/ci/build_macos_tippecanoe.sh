#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  echo "usage: build_macos_tippecanoe.sh SOURCE_ARCHIVE OUTPUT_DIRECTORY" >&2
  exit 2
fi

source_archive="$1"
output_directory="$2"
xcode_root="/Applications/Xcode_15.4.app/Contents/Developer"
expected_source_sha="b0fd9df49b6efc988288ea48774822c6de19eb48428017f27ee0b3b01d44f05d"

test "$(uname -s)" = "Darwin"
test "$(uname -m)" = "arm64"
test -d "${xcode_root}"
printf '%s  %s\n' "${expected_source_sha}" "${source_archive}" | shasum -a 256 -c -

build_root="$(mktemp -d "${RUNNER_TEMP:-/tmp}/tippecanoe-2.79.0-build.XXXXXX")"
trap 'rm -rf -- "${build_root}"' EXIT
tar -xzf "${source_archive}" -C "${build_root}" --strip-components=1

export DEVELOPER_DIR="${xcode_root}"
export LC_ALL=C
export SDKROOT="$(xcrun --sdk macosx --show-sdk-path)"
export TZ=UTC
cc="$(xcrun --find clang)"
cxx="$(xcrun --find clang++)"

xcodebuild -version
"${cxx}" --version | head -n 1
make -C "${build_root}" -j4 CC="${cc}" CXX="${cxx}" tippecanoe tippecanoe-decode

mkdir -p "${output_directory}"
install -m 0755 "${build_root}/tippecanoe" "${output_directory}/tippecanoe"
install -m 0755 "${build_root}/tippecanoe-decode" "${output_directory}/tippecanoe-decode"
shasum -a 256 "${output_directory}/tippecanoe" "${output_directory}/tippecanoe-decode"
