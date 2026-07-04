#!/bin/bash
set -e

echo "Starting AWS resource cleanup..."

SKIP_VPC=false
SKIP_IAM=false
SKIP_SG=false
SKIP_DB=false

for arg in "$@"; do
  case $arg in
    --skip-vpc)
      SKIP_VPC=true
      shift
      ;;
    --skip-iam)
      SKIP_IAM=true
      shift
      ;;
    --skip-sg)
      SKIP_SG=true
      shift
      ;;
    --skip-db)
      SKIP_DB=true
      shift
      ;;
  esac
done

if [ "$SKIP_VPC" = true ]; then
  echo "Untracking VPC and Subnets from Terraform state..."
  terraform state rm 'aws_vpc.main[0]' || true
  terraform state rm 'aws_internet_gateway.main[0]' || true
  terraform state rm 'aws_subnet.public[0]' || true
  terraform state rm 'aws_subnet.public[1]' || true
  terraform state rm 'aws_route_table.public[0]' || true
  terraform state rm 'aws_route_table_association.public[0]' || true
  terraform state rm 'aws_route_table_association.public[1]' || true
fi

if [ "$SKIP_IAM" = true ]; then
  echo "Untracking IAM Role and Instance Profile from Terraform state..."
  terraform state rm 'aws_iam_role.photoz_ec2_role[0]' || true
  terraform state rm 'aws_iam_role_policy_attachment.cloudwatch_access[0]' || true
  terraform state rm 'aws_iam_instance_profile.photoz_profile[0]' || true
fi

if [ "$SKIP_SG" = true ]; then
  echo "Untracking Security Groups from Terraform state..."
  terraform state rm 'aws_security_group.lb[0]' || true
  terraform state rm 'aws_security_group.app[0]' || true
  terraform state rm 'aws_security_group.db[0]' || true
fi

if [ "$SKIP_DB" = true ]; then
  echo "Untracking Database Node from Terraform state..."
  terraform state rm 'aws_instance.db_node[0]' || true
fi

echo "Proceeding with terraform destroy for remaining resources..."
terraform destroy
