# The Sentinel cloud hub: one hardened Graviton instance in its own VPC.
#
#   internet --443/80--> Caddy (TLS, Let's Encrypt) --127.0.0.1:8000--> sentinel
#   edge nodes --7422 (allow-listed; no leaf TLS yet, SC-8)--> nats-server leafnode
#   admin --22 from admin_cidr only--> sshd;  SSM Session Manager as the break-glass path
#
# Deliberately small. The same bundle that installs here installs on an edge
# laptop and in a disconnected enclave; only the role and the network differ.

data "aws_ssm_parameter" "ubuntu_arm64" {
  # Canonical's published pointer to the current Ubuntu 24.04 LTS arm64 AMI.
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id"
}

data "aws_availability_zones" "available" {
  state = "available"
}

# --------------------------------------------------------------- network ----
resource "aws_vpc" "this" {
  cidr_block           = "10.40.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = var.name }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = var.name }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = "10.40.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = false
  tags                    = { Name = "${var.name}-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }
  tags = { Name = "${var.name}-public" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "hub" {
  name        = "${var.name}-sg"
  description = "Sentinel hub: HTTPS for the console, SSH from admin only, leaf port by allow-list"
  vpc_id      = aws_vpc.this.id
  tags        = { Name = "${var.name}-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  security_group_id = aws_security_group.hub.id
  description       = "Console and API over TLS"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_ingress_rule" "http_acme" {
  security_group_id = aws_security_group.hub.id
  description       = "ACME HTTP-01 challenge and redirect to HTTPS"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_ingress_rule" "ssh_admin" {
  security_group_id = aws_security_group.hub.id
  description       = "SSH from the admin network only"
  cidr_ipv4         = var.admin_cidr
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
}

resource "aws_vpc_security_group_ingress_rule" "nats_leaf" {
  for_each          = toset(var.leaf_allowed_cidrs)
  security_group_id = aws_security_group.hub.id
  description       = "NATS leafnode from an allow-listed edge (no TLS yet, SC-8)"
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 7422
  to_port           = 7422
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.hub.id
  description       = "Package updates, ACME, CelesTrak"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# ------------------------------------------------------------------- IAM ----
data "aws_iam_policy_document" "assume_ec2" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "hub" {
  name               = "${var.name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume_ec2.json
}

# Least privilege: Session Manager only. No S3, no secrets, no admin.
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.hub.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "hub" {
  name = "${var.name}-profile"
  role = aws_iam_role.hub.name
}

# -------------------------------------------------------------- instance ----
resource "aws_key_pair" "admin" {
  key_name   = "${var.name}-admin"
  public_key = var.ssh_public_key
}

resource "aws_instance" "hub" {
  ami                    = data.aws_ssm_parameter.ubuntu_arm64.value
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.hub.id]
  iam_instance_profile   = aws_iam_instance_profile.hub.name
  key_name               = aws_key_pair.admin.key_name
  monitoring             = false

  metadata_options {
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 1
    http_endpoint               = "enabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb
    encrypted             = true
    delete_on_termination = true
  }

  user_data = <<-EOT
    #cloud-config
    package_update: true
    packages: [python3.12, python3.12-venv, caddy, unattended-upgrades]
  EOT

  lifecycle {
    ignore_changes = [ami] # the SSM pointer moves; rebuild deliberately, not on every plan
  }

  tags = { Name = var.name }
}

resource "aws_eip" "hub" {
  domain   = "vpc"
  instance = aws_instance.hub.id
  tags     = { Name = var.name }
}

# ---------------------------------------------------------------- budget ----
resource "aws_budgets_budget" "monthly" {
  name         = "${var.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Project$sentinel"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }
}
