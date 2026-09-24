terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
  # Local state by default (gitignored). For a team: an S3 backend with
  # versioning and a DynamoDB lock table. For GovCloud: the same code with
  # region us-gov-west-1 and the aws-us-gov partition.
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project     = "sentinel"
      Environment = var.environment
      ManagedBy   = "terraform"
      DataClass   = "unclassified-exercise"
    }
  }
}
