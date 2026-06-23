#!/usr/bin/env bash
# Build the guest rootfs (images/rootfs.ext4) WITHOUT root:
#   docker export python:alpine -> staging dir -> inject init/runner -> mke2fs -d
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
IMG="$ROOT/images/rootfs.ext4"
IMAGE="${BASE_IMAGE:-python:3.12-alpine}"
SIZE="${ROOTFS_SIZE:-384M}"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo ">> pulling $IMAGE"
docker pull -q "$IMAGE"

echo ">> exporting filesystem"
CID="$(docker create "$IMAGE" /bin/true)"
docker export "$CID" | tar -x -C "$STAGE"
docker rm "$CID" >/dev/null

echo ">> injecting init + runner"
install -m 0755 "$HERE/guest_init.sh" "$STAGE/init"
install -m 0755 "$HERE/guest_runner.py" "$STAGE/runner.py"
mkdir -p "$STAGE/job" "$STAGE/proc" "$STAGE/sys" "$STAGE/dev" "$STAGE/tmp"

echo ">> building ext4 image ($SIZE) at $IMG"
mkdir -p "$ROOT/images"
rm -f "$IMG"
mke2fs -q -F -t ext4 -d "$STAGE" "$IMG" "$SIZE"

echo ">> done: $IMG"
ls -lh "$IMG"
