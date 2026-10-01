"""Configuration and secret loading.

On AWS the container receives only two Secrets Manager ARNs (DB_SECRET_ARN, APP_SECRET_ARN).
The app reads the values at runtime through the EC2 instance role, and re-reads the DB secret
if RDS rotates the password. Locally (docker compose) plain environment variables are used.
"""
import json
import os

_db_cache = None


def get_secret(arn):
    import boto3  # lazy: local development and unit tests do not need AWS

    client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "ap-south-1"))
    return client.get_secret_value(SecretId=arn)["SecretString"]


def db_settings():
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "database": os.getenv("DB_NAME", "careconnect"),
    }


def db_credentials(force_refresh=False):
    global _db_cache
    arn = os.getenv("DB_SECRET_ARN")
    if not arn:
        return os.getenv("DB_USER", "root"), os.getenv("DB_PASSWORD", "")
    if force_refresh or _db_cache is None:
        data = json.loads(get_secret(arn))
        _db_cache = (data["username"], data["password"])
    return _db_cache


def flask_secret_key():
    if os.getenv("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    arn = os.getenv("APP_SECRET_ARN")
    if arn:
        return get_secret(arn)  # same value on every instance, so sessions work behind the ALB
    return "dev-only-secret-change-me"
