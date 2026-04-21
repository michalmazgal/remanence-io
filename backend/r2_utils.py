import boto3
from botocore.config import Config
import os

def get_r2_config():
    secrets = {}
    with open("/root/.heatsun_secrets", "r") as f:
        for line in f:
            if "=" in line:
                key, value = line.strip().split("=", 1)
                secrets[key] = value
    return secrets

def generate_presigned_url(blob_name: str, expires_in: int = 3600):
    config = get_r2_config()
    
    s3 = boto3.client(
        "s3",
        endpoint_url=config["R2_ENDPOINT"],
        aws_access_key_id=config["R2_ACCESS_KEY"],
        aws_secret_access_key=config["R2_SECRET_KEY"],
        config=Config(signature_version="s3v4"),
    )
    
    url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": config["R2_BUCKET"], "Key": blob_name},
        ExpiresIn=expires_in,
    )
    return url
