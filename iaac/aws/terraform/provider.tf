# This file configures Terraform "providers", which are the plugins Terraform uses 
# to interact with cloud platforms and APIs. 
# Here, we declare the official HashiCorp AWS provider (version 5.0+) and configure 
# it to deploy our infrastructure into the region defined by `var.aws_region`.

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region     = var.aws_region
  access_key = var.aws_access_key_id
  secret_key = var.aws_secret_access_key

  default_tags {
    tags = {
      Environment = terraform.workspace == "default" ? "prod" : terraform.workspace
    }
  }
}
