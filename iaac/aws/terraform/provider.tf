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
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

provider "aws" {
  region     = var.aws_region

  default_tags {
    tags = {
      Environment = terraform.workspace == "default" ? "prod" : terraform.workspace
    }
  }
}
