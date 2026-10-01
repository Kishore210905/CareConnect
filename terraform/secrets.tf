# Session-signing key shared by every app instance (so a login works on any server behind the ALB).
resource "random_password" "flask_secret" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "flask_secret" {
  name                    = "${var.project_name}/flask-secret-key"
  recovery_window_in_days = 0 # lab: delete immediately on destroy so the name can be reused
}

resource "aws_secretsmanager_secret_version" "flask_secret" {
  secret_id     = aws_secretsmanager_secret.flask_secret.id
  secret_string = random_password.flask_secret.result
}
