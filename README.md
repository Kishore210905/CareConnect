# CareConnect: Self-Healing Three-Tier Healthcare Management System on AWS

Flask + MySQL healthcare app (register/login, doctors, appointment booking/cancel, medication tracker)
deployed with Docker, Terraform, ECR, private RDS, ALB, EC2 Auto Scaling, CloudWatch, SNS and GitHub Actions (OIDC).
Region: **ap-south-1**. Demo software: do not store real patient data.

```
Internet -> ALB (public subnets) -> EC2 x2 (private, Docker+Flask, ASG 2-4) -> RDS MySQL (private)
GitHub -> Actions -> ECR -> ASG instance refresh      CloudWatch -> SNS -> email
```

Commands below are PowerShell (Windows). Bash users: same commands; see the notes where syntax differs.

---
## PART A: Local (do this first)

### A1. Tools
Git, Python 3.12, Docker Desktop, Terraform >= 1.6, AWS CLI v2, VS Code. Verify:

    git --version; python --version; docker --version; terraform -version; aws --version
    aws configure          # access key of an admin lab user, region ap-south-1
    aws sts get-caller-identity

### A2. Run the unit tests
    cd D:\project\careconnect
    python -m venv venv
    venv\Scripts\activate
    pip install -r app\requirements.txt pytest
    python -m pytest -v          # 18 tests, no database needed

### A3. Run the full app locally (app + MySQL)
    docker compose up --build    # open http://localhost:5000
Register, log in, book an appointment, add a medication. Tables and 5 sample doctors are created automatically
from `database/schema.sql` on first use. Stop with Ctrl+C then `docker compose down -v`.

Do not move on until this works.

### A4. Push to GitHub
Create an empty GitHub repo named `careconnect`, then:

    git init; git branch -M main; git add .; git commit -m "Initial CareConnect application"
    git remote add origin https://github.com/YOUR_USERNAME/careconnect.git
    git push -u origin main
(The first Actions run fails at the AWS step: the role doesn't exist yet. Expected.)

---
## PART B: Deploy on AWS

### B1. Configure
    cd terraform
    Copy-Item terraform.tfvars.example terraform.tfvars
Edit `terraform.tfvars`: `alert_email` (your email) and `github_repo` (`YOUR_USERNAME/careconnect`).
If your AWS account already has the GitHub OIDC provider, set `create_github_oidc_provider = false`.

### B2. Create ECR first (instances need an image to pull)
    terraform init
    terraform validate
    terraform apply "-target=aws_ecr_repository.app"

### B3. Build and push the first image
    $ECR = terraform output -raw ecr_repository_url
    $REGISTRY = $ECR.Split("/")[0]
    aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin $REGISTRY
    cd ..
    docker build --build-arg APP_VERSION=1.0.0 -t "${ECR}:latest" .
    docker push "${ECR}:latest"
    cd terraform

### B4. Create everything else (about 10-15 min; RDS is slowest)
    terraform fmt
    terraform plan
    terraform apply

### B5. After apply
1. **Confirm the SNS email** AWS sent you (alerts do not work until you click it).
2. `terraform output`: note `alb_url`, `github_actions_role_arn`, `cloudwatch_dashboard`.
3. GitHub repo -> Settings -> Secrets and variables -> Actions -> New secret: `AWS_ROLE_ARN` = the role ARN.

### B6. Verify (allow ~5 min for instances to boot)
    $ALB = terraform output -raw alb_url
    curl.exe "$ALB/health"; curl.exe "$ALB/version"; curl.exe "$ALB/db"     # /db -> "connected"
Open `$ALB` in a browser: register -> login -> doctors -> book -> appointments -> cancel -> medications.
Console: EC2 -> Target Groups -> `careconnect-tg` -> Targets: **2 healthy**. Reload the page: the footer's
"Served by" host changes between the two instances and you stay logged in (shared session key).
Confirm RDS is private: RDS -> `careconnect-mysql` -> Publicly accessible = **No**.

---
## PART C: CI/CD test
Edit `VERSION` (e.g. `1.1.0`), then:

    git add .; git commit -m "Release 1.1.0"; git push

Actions tab: test -> build -> push to ECR -> instance refresh (rolling, no downtime). Then `curl.exe "$ALB/version"`
shows `1.1.0+<commit>`.

## PART D: Auto scaling demo
    1..6 | ForEach-Object {
      1..12 | ForEach-Object { Start-Job { param($u) Invoke-WebRequest -UseBasicParsing "$u/stress?seconds=50" } -ArgumentList $ALB } | Wait-Job | Out-Null
    }
(Bash: `for r in 1 2 3 4 5 6; do for i in $(seq 12); do curl -s "$ALB/stress?seconds=50" >/dev/null & done; wait; done`)
Watch EC2 -> Auto Scaling groups -> `careconnect-asg` -> Activity, or the CloudWatch dashboard. After ~3-5 min of >70% CPU
the group grows (max 4); it shrinks ~15 min after load stops.

## PART E: Self-healing demo
    $ASG = terraform output -raw asg_name
    aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names $ASG --query "AutoScalingGroups[0].Instances[].[InstanceId,HealthStatus]" --output table

Test 1: terminate an instance

    aws ec2 terminate-instances --instance-ids i-XXXXXXXX

Test 2: stop only the container

    aws ssm send-command --instance-ids i-XXXXXXXX --document-name AWS-RunShellScript --parameters commands="docker stop careconnect"

Expected: ALB marks it unhealthy -> ASG launches a replacement -> User Data starts Docker -> `/health` 200 -> target
healthy. The site stays up on the other instance throughout; SNS emails arrive (unhealthy-host alarm, instance
terminate/launch).

## PART F: Cleanup (NAT, ALB, RDS and EC2 bill hourly)
    cd terraform
    terraform destroy

---
## Troubleshooting (502 / unhealthy targets)
Check one layer at a time. Use SSM (no SSH): `aws ssm start-session --target i-XXXX` (needs the Session Manager plugin), then:

    sudo cat /var/log/user-data.log          # boot script: ECR login, image pull
    sudo docker ps ; sudo docker logs careconnect
    curl localhost:5000/health ; curl localhost:5000/db

| Symptom | Likely cause |
|---|---|
| user-data log: pull access denied / not found | First image not pushed (do B3) or IAM/ECR region mismatch |
| container exits, log mentions Secrets Manager / AccessDenied | Instance role policy or `http_put_response_hop_limit = 2` missing |
| `/db` returns unreachable | RDS still creating, or RDS SG does not allow the app SG on 3306 |
| Targets unhealthy, container running | App SG must allow 5000 from the ALB SG; target group port 5000, path `/health` |
| Actions: "Not authorized to perform sts:AssumeRoleWithWebIdentity" | `github_repo` in tfvars must match `owner/repo`; only the `main` branch may deploy |
| Instance refresh "already in progress" | Wait or cancel it in the console |

## Security design
- RDS private, encrypted, reachable only from the app security group (3306). ALB -> EC2 (5000) -> RDS (3306).
- DB password is RDS-managed (Secrets Manager, auto-rotated). The session key is generated by Terraform (Secrets Manager).
  The container receives only the secret ARNs and reads the values via the EC2 instance role (no secrets in user data,
  tfvars or Git). The app re-reads the DB secret if rotation causes an auth failure.
- App: hashed passwords, CSRF tokens on all forms, POST-only state changes, parameterised SQL, per-user data isolation,
  CSP/X-Frame-Options headers, no-store cache on personal pages.
- Pipeline: GitHub OIDC, role limited to repo `main` branch. No SSH open; use SSM Session Manager. IMDSv2 enforced.

## Lab shortcuts (change for production)
HTTP only (add ACM certificate + HTTPS listener, then set `SESSION_COOKIE_SECURE=True`), single NAT gateway, single-AZ
RDS, `skip_final_snapshot`, `/stress` endpoint enabled (`enable_stress_endpoint = false`), no login rate limiting / WAF.
Real healthcare data would additionally require HIPAA-style controls, audit logging, and encryption review.

## Repository layout
```
careconnect/
  app/ (app.py, db.py, config.py, requirements.txt)   templates/   static/ (style.css, app.js)
  database/schema.sql   tests/test_app.py   VERSION   Dockerfile   docker-compose.yml
  terraform/ (provider, variables, vpc, security_groups, iam, ecr, rds, secrets, alb, asg, monitoring, sns,
              outputs, user_data.sh.tftpl, terraform.tfvars.example)
  .github/workflows/deploy.yml
```

## Resume description
Built and deployed a containerized Flask + MySQL healthcare appointment platform on AWS using Terraform, Docker, ECR,
EC2 Auto Scaling, Application Load Balancer and private RDS. Implemented GitHub Actions CI/CD with OIDC authentication
and zero-downtime rolling instance refresh, Secrets Manager credential handling with rotation-aware reconnects,
CloudWatch dashboards/alarms with SNS alerting, and verified automatic replacement of failed instances.
