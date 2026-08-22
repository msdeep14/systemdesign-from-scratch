terraform {
  backend "s3" {
    bucket       = "bses-v0-terraform-state"
    key          = "state/terraform.tfstate"
    region       = "ap-south-1"
    use_lockfile = true
  }
}
