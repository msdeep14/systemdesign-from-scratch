# CDN: CloudFront in Front of S3

## Overview

Without a CDN, every image load is a direct S3 fetch from `ap-south-1` (Mumbai)

CloudFront has 600+ edge locations (Points of Presence). After the first request, the photo is cached at the nearest edge. Subsequent requests from the same region never touch S3.

## How It Works

### Origin Access Control (OAC)

The S3 bucket is NOT publicly accessible. CloudFront uses an Origin Access Control identity to authenticate with S3. Only CloudFront can read from the bucket.

This is configured in `iaac/aws/terraform/cloudfront.tf`:
- `aws_cloudfront_origin_access_control` — the identity CloudFront uses
- `aws_s3_bucket_policy` — allows only this specific CloudFront distribution to `s3:GetObject`

### URL Generation (django-storages)

The `AWS_S3_CUSTOM_DOMAIN` setting in Django makes `django-storages` replace the S3 domain in all generated URLs:

- Before: `https://s3.ap-south-1.amazonaws.com/bucket/photos/42/photo_abc.jpg`
- After: `https://d1234abcdef.cloudfront.net/photos/42/photo_abc.jpg`

No template changes needed. All templates use `{{ photo.image.url }}` which resolves automatically.

### Cache Invalidation on Photo Delete

When a user deletes a photo, the S3 object is deleted. But CloudFront might still serve the cached copy from its edge locations for up to 24 hours (default TTL).

To handle this, the `delete_photo` view calls `cdn.invalidate_cache(image_path)` which triggers a CloudFront invalidation API call via `boto3`. This tells CloudFront to purge that specific path from all 600+ edge locations.

The wrapper is in `photoz/photos/cdn.py`. It is a no-op when `CLOUDFRONT_DISTRIBUTION_ID` is not set (local dev).

### Caching Policy

Using AWS Managed `CachingOptimized` policy:
- Default TTL: 24 hours
- Max TTL: 1 year

---

## Terraform Resources

> [!NOTE]
> The AWS IAM user running Terraform must have the `CloudFrontFullAccess` managed policy attached to successfully create the CloudFront distribution and OAC.

---

## Benchmarking: CDN vs Direct S3

```bash
# Get a photo URL from the app (right-click image > Copy Image Address)
# Construct the S3 URL by replacing the CloudFront domain with the S3 domain

S3_URL="https://s3.ap-south-1.amazonaws.com/<bucket>/photos/42/photo_abc.jpg"
CDN_URL="https://<distribution>.cloudfront.net/photos/42/photo_abc.jpg"

python chapter04/caching/cdn/benchmark_cdn.py \
    --s3-url "$S3_URL" \
    --cdn-url "$CDN_URL" \
    --requests 20
```

```bash
# Measure TTFB for direct S3
curl -o /dev/null -s -w "TTFB: %{time_starttransfer}s  Total: %{time_total}s\n" \
  "https://s3.ap-south-1.amazonaws.com/<bucket>/photos/42/photo_abc.jpg"

# Measure TTFB for CloudFront
curl -o /dev/null -s -w "TTFB: %{time_starttransfer}s  Total: %{time_total}s\n" \
  "https://<distribution>.cloudfront.net/photos/42/photo_abc.jpg"

# Check cache HIT/MISS
curl -I "https://<distribution>.cloudfront.net/photos/42/photo_abc.jpg" 2>/dev/null | grep x-cache
```
