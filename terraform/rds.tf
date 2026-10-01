resource "aws_db_subnet_group" "main" {
  name       = "${var.project_name}-db-subnets"
  subnet_ids = aws_subnet.db[*].id
}

resource "aws_db_instance" "mysql" {
  identifier             = "${var.project_name}-mysql"
  engine                 = "mysql"
  engine_version         = "8.0"
  instance_class         = var.db_instance_class
  allocated_storage      = 20
  storage_encrypted      = true
  db_name                = "careconnect"
  username               = "admin"
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  multi_az               = false # set true for real production
  skip_final_snapshot    = true  # lab only
  deletion_protection    = false # lab only

  # RDS generates the password and keeps it in Secrets Manager. Nothing in Git or tfvars.
  manage_master_user_password = true
}
