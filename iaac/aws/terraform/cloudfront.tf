resource "aws_cloudfront_origin_access_control" "photoz" {
  name                              = "photoz-s3-oac${local.env_suffix}"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "photoz_cdn" {
  enabled = true
  comment = "CDN for PhotoZ media files"

  origin {
    domain_name              = "${local.s3_bucket_name}.s3.${var.aws_region}.amazonaws.com"
    origin_id                = "S3-photoz-media"
    origin_access_control_id = aws_cloudfront_origin_access_control.photoz.id
  }

  default_cache_behavior {
    allowed_methods  = ["GET", "HEAD"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "S3-photoz-media"

    # AWS Managed CachingOptimized policy
    # Default TTL: 24h, Max TTL: 1 year
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"

    viewer_protocol_policy = "https-only"
    compress               = true
  }

  # PriceClass_200 covers US, Canada, Europe, Asia, Middle East, Africa.
  # Excludes South America and Australia (cheapest option with Asia coverage).
  price_class = "PriceClass_200"

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# S3 bucket policy: Allow only CloudFront OAC to read objects.
# Even though the bucket itself is managed manually, Terraform handles applying
# the bucket policy dynamically to ensure the CloudFront ARN is always correct.
resource "aws_s3_bucket_policy" "allow_cloudfront" {
  bucket = local.s3_bucket_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudFrontOAC"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "arn:aws:s3:::${local.s3_bucket_name}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.photoz_cdn.arn
          }
        }
      }
    ]
  })
}

