resource "aws_sns_topic" "alerts" {
  name = "${var.project_name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email # you must click the confirmation link AWS emails you
}

# Email on every instance launch / terminate: you see self-healing happen.
resource "aws_autoscaling_notification" "events" {
  group_names = [aws_autoscaling_group.app.name]
  topic_arn   = aws_sns_topic.alerts.arn
  notifications = [
    "autoscaling:EC2_INSTANCE_LAUNCH",
    "autoscaling:EC2_INSTANCE_TERMINATE",
    "autoscaling:EC2_INSTANCE_LAUNCH_ERROR",
    "autoscaling:EC2_INSTANCE_TERMINATE_ERROR",
  ]
}
