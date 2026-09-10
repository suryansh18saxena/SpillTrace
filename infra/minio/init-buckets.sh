#!/bin/sh
# Create the SPILLTRACE bucket and prefixes.  Idempotent.
set -eu
mc alias set local http://minio:9000 "$S3_ACCESS_KEY" "$S3_SECRET_KEY"
mc mb --ignore-existing "local/$S3_BUCKET"
# Private by default: presigned URLs are issued by the API (NFR-009).
mc anonymous set none "local/$S3_BUCKET" || true
for p in scenes tiles masks probability environment drift reports models; do
  printf '' | mc pipe "local/$S3_BUCKET/$p/.keep"
done
echo "minio-init: bucket '$S3_BUCKET' ready"
