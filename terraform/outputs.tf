output "alb_url" {
  value = "http://${aws_lb.app.dns_name}"
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "asg_name" {
  value = aws_autoscaling_group.app.name
}

output "github_actions_role_arn" {
  value = aws_iam_role.github_actions.arn
}

output "rds_endpoint" {
  value = aws_db_instance.mysql.address
}

output "sns_topic_arn" {
  value = aws_sns_topic.alerts.arn
}

output "cloudwatch_dashboard" {
  value = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${aws_cloudwatch_dashboard.main.dashboard_name}"
}
