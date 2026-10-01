variable "aws_region" {
  type    = string
  default = "ap-south-1"
}

variable "project_name" {
  type    = string
  default = "careconnect"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "instance_type" {
  type    = string
  default = "t3.micro"
}

variable "db_instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "asg_min" {
  type    = number
  default = 2
}

variable "asg_desired" {
  type    = number
  default = 2
}

variable "asg_max" {
  type    = number
  default = 4
}

variable "alert_email" {
  type        = string
  description = "Email address that receives SNS alerts"
}

variable "github_repo" {
  type        = string
  description = "GitHub repo allowed to deploy, format: owner/repo"
}

variable "create_github_oidc_provider" {
  type        = bool
  default     = true
  description = "Set false if the account already has the GitHub OIDC provider"
}

variable "enable_stress_endpoint" {
  type        = bool
  default     = true
  description = "Lab only: enables /stress endpoint for the auto scaling demo"
}
