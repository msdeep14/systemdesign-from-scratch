resource "aws_iam_role" "photoz_ec2_role" {
  count = var.create_iam_role ? 1 : 0
  name  = "photoz-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "cloudwatch_access" {
  count      = var.create_iam_role ? 1 : 0
  role       = aws_iam_role.photoz_ec2_role[0].name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess"
}

resource "aws_iam_role_policy_attachment" "s3_access" {
  count      = var.create_iam_role ? 1 : 0
  role       = aws_iam_role.photoz_ec2_role[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}

resource "aws_iam_role_policy" "cloudfront_invalidation" {
  count = var.create_iam_role ? 1 : 0
  name  = "cloudfront-invalidation"
  role  = aws_iam_role.photoz_ec2_role[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "cloudfront:CreateInvalidation"
        Resource = aws_cloudfront_distribution.photoz_cdn.arn
      }
    ]
  })
}

resource "aws_iam_role_policy" "runner_deploy_access" {
  count = var.create_iam_role ? 1 : 0
  name  = "runner-deploy-access"
  role  = aws_iam_role.photoz_ec2_role[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = [
          "ec2:DescribeInstances",
          "autoscaling:StartInstanceRefresh"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_instance_profile" "photoz_profile" {
  count = var.create_iam_role ? 1 : 0
  name  = "photoz-ec2-profile"
  role  = aws_iam_role.photoz_ec2_role[0].name
}

locals {
  iam_instance_profile = var.create_iam_role ? aws_iam_instance_profile.photoz_profile[0].name : var.existing_iam_instance_profile_name
}
