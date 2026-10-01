data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_launch_template" "app" {
  name_prefix            = "${var.project_name}-lt-"
  image_id               = data.aws_ssm_parameter.al2023.value
  instance_type          = var.instance_type
  vpc_security_group_ids = [aws_security_group.ec2.id]
  update_default_version = true

  iam_instance_profile {
    name = aws_iam_instance_profile.ec2.name
  }

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required" # IMDSv2 only
    # hop limit 2 lets the app *inside the Docker container* use the instance role (boto3)
    http_put_response_hop_limit = 2
  }

  user_data = base64encode(templatefile("${path.module}/user_data.sh.tftpl", {
    aws_region     = var.aws_region
    ecr_repo_url   = aws_ecr_repository.app.repository_url
    ecr_registry   = split("/", aws_ecr_repository.app.repository_url)[0]
    db_secret_arn  = aws_db_instance.mysql.master_user_secret[0].secret_arn
    app_secret_arn = aws_secretsmanager_secret.flask_secret.arn
    db_host        = aws_db_instance.mysql.address
    db_name        = aws_db_instance.mysql.db_name
    enable_stress  = var.enable_stress_endpoint
  }))

  tag_specifications {
    resource_type = "instance"
    tags          = { Name = "${var.project_name}-app" }
  }
}

resource "aws_autoscaling_group" "app" {
  name                      = "${var.project_name}-asg"
  min_size                  = var.asg_min
  desired_capacity          = var.asg_desired
  max_size                  = var.asg_max
  vpc_zone_identifier       = aws_subnet.app[*].id
  target_group_arns         = [aws_lb_target_group.app.arn]
  health_check_type         = "ELB" # ALB health failures trigger replacement
  health_check_grace_period = 300
  metrics_granularity       = "1Minute"
  enabled_metrics = [
    "GroupMinSize", "GroupMaxSize", "GroupDesiredCapacity",
    "GroupInServiceInstances", "GroupTotalInstances"
  ]

  launch_template {
    id      = aws_launch_template.app.id
    version = aws_launch_template.app.latest_version
  }

  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
      instance_warmup        = 120
    }
  }

  tag {
    key                 = "Name"
    value               = "${var.project_name}-app"
    propagate_at_launch = true
  }

  depends_on = [aws_nat_gateway.nat, aws_db_instance.mysql, aws_secretsmanager_secret_version.flask_secret]
}

resource "aws_autoscaling_policy" "cpu" {
  name                   = "${var.project_name}-cpu-target"
  autoscaling_group_name = aws_autoscaling_group.app.name
  policy_type            = "TargetTrackingScaling"

  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ASGAverageCPUUtilization"
    }
    target_value = 70
  }
}
