resource "aws_vpc" "main" {
  count                = var.create_vpc ? 1 : 0
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags = { Name = "photoz-vpc${local.env_suffix}" }
}

resource "aws_internet_gateway" "main" {
  count  = var.create_vpc ? 1 : 0
  vpc_id = aws_vpc.main[0].id
  tags = { Name = "photoz-igw${local.env_suffix}" }
}

resource "aws_subnet" "public" {
  count                   = var.create_vpc ? 2 : 0
  vpc_id                  = aws_vpc.main[0].id
  cidr_block              = cidrsubnet(aws_vpc.main[0].cidr_block, 8, count.index)
  map_public_ip_on_launch = true
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  tags = { Name = "photoz-public-subnet-${count.index + 1}${local.env_suffix}" }
}

resource "aws_route_table" "public" {
  count  = var.create_vpc ? 1 : 0
  vpc_id = aws_vpc.main[0].id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main[0].id
  }
  tags = { Name = "photoz-public-rt${local.env_suffix}" }
}

resource "aws_route_table_association" "public" {
  count          = var.create_vpc ? 2 : 0
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public[0].id
}

data "aws_availability_zones" "available" {
  state = "available"
}

# Locals to abstract created vs existing resources
locals {
  vpc_id     = var.create_vpc ? aws_vpc.main[0].id : var.existing_vpc_id
  subnet_ids = var.create_vpc ? aws_subnet.public[*].id : var.existing_public_subnet_ids
}
