#!/usr/bin/env bash
# Download an uncompressed Firecracker-compatible guest kernel (vmlinux).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
DEST="$ROOT/images/vmlinux.bin"
URL="${KERNEL_URL:-https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.10/x86_64/vmlinux-6.1.102}"

mkdir -p "$ROOT/images"
echo ">> fetching kernel from $URL"
curl -fSL "$URL" -o "$DEST"
echo ">> done: $DEST"
ls -lh "$DEST"
