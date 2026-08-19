resource "aws_iam_role" "photoz_ec2_role" {
  count = var.create_iam_role ? 1 : 0
  name  = "photoz-ec2-role${local.env_suffix}"

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

resource "aws_iam_role_policy_attachment" "ssm_core" {
  count      = var.create_iam_role ? 1 : 0
  role       = aws_iam_role.photoz_ec2_role[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "s3_access" {
  count = var.create_iam_role ? 1 : 0
  name  = "s3-access${local.env_suffix}"
  role  = aws_iam_role.photoz_ec2_role[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::${local.s3_bucket_name}",
          "arn:aws:s3:::${local.s3_bucket_name}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "cloudfront_invalidation" {
  count = var.create_iam_role ? 1 : 0
  name  = "cloudfront-invalidation${local.env_suffix}"
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
  name  = "runner-deploy-access${local.env_suffix}"
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
  name  = "photoz-ec2-profile${local.env_suffix}"
  role  = aws_iam_role.photoz_ec2_role[0].name
}

locals {
  iam_instance_profile = var.create_iam_role ? aws_iam_instance_profile.photoz_profile[0].name : var.existing_iam_instance_profile_name
}

# ==========================================
# GitHub Actions OIDC Configuration
# ==========================================

data "tls_certificate" "github" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github.certificates[0].sha1_fingerprint]
}

resource "aws_iam_role" "github_actions_deployer" {
  name = "github-actions-deployer-role${local.env_suffix}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.github_actions.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringLike = {
            "token.actions.githubusercontent.com:sub" = "repo:msdeep14/systemdesign-from-scratch:*"
          }
          StringEquals = {
            "token.actions.githubusercontent.com:aud"   = "sts.amazonaws.com"
            "token.actions.githubusercontent.com:actor" = "msdeep14"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "github_actions_deployer_policy" {
  name = "github-actions-deployer-policy${local.env_suffix}"
  role = aws_iam_role.github_actions_deployer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ec2:DescribeInstances",
          "ec2:StartInstances",
          "ec2:StopInstances",
          "autoscaling:DescribeAutoScalingGroups",
          "autoscaling:UpdateAutoScalingGroup",
          "autoscaling:StartInstanceRefresh",
          "ssm:GetParameter",
          "ssm:SendCommand",
          "ssm:GetCommandInvocation"
        ]
        Resource = "*"
      }
    ]
  })
}
