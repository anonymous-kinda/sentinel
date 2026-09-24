variable "region" {
  description = "AWS region for the cloud hub."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  type    = string
  default = "demo"
}

variable "name" {
  type    = string
  default = "sentinel-hub"
}

variable "instance_type" {
  description = "Graviton (arm64). t4g.small is 2 vCPU / 2 GiB - enough for the hub."
  type        = string
  default     = "t4g.small"
}

variable "admin_cidr" {
  description = "The only network allowed to SSH to the host, e.g. \"203.0.113.10/32\". Required."
  type        = string
  validation {
    condition     = can(cidrhost(var.admin_cidr, 0)) && var.admin_cidr != "0.0.0.0/0"
    error_message = "admin_cidr must be a specific CIDR, never 0.0.0.0/0."
  }
}

variable "ssh_public_key" {
  description = "OpenSSH public key for the admin account (contents, not a path)."
  type        = string
}

variable "leaf_allowed_cidrs" {
  description = "Networks allowed to reach the NATS leaf port (7422; no TLS yet, SC-8). Empty keeps it closed."
  type        = list(string)
  default     = []
}

variable "budget_email" {
  description = "Where the monthly budget alarm is sent."
  type        = string
}

variable "monthly_budget_usd" {
  type    = number
  default = 20
}

variable "root_volume_gb" {
  type    = number
  default = 20
}
