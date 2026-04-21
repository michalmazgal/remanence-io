import boto3
import os
from botocore.exceptions import ClientError

def test_r2_connection():
    # Load keys from secrets file manually to avoid env issues in this test
    secrets = {}
    with open('/root/.heatsun_secrets', 'r') as f:
        for line in f:
            if '=' in line:
                k, v = line.strip().split('=', 1)
                secrets[k] = v

    r2_access_key = secrets.get('R2_ACCESS_KEY')
    r2_secret_key = secrets.get('R2_SECRET_KEY')
    r2_endpoint = secrets.get('R2_ENDPOINT')
    r2_bucket = secrets.get('R2_BUCKET')

    print(f"Testing connection to R2 bucket: {r2_bucket}...")

    try:
        s3 = boto3.client(
            's3',
            aws_access_key_id=r2_access_key,
            aws_secret_access_key=r2_secret_key,
            endpoint_url=r2_endpoint
        )
        
        # Try to list objects
        response = s3.list_objects_v2(Bucket=r2_bucket)
        print("Successfully connected to R2 and listed objects.")
        
        # Try to upload a small test file
        test_file = 'r2_test_conn.txt'
        with open(test_file, 'w') as f:
            f.write('Connection test successful')
        
        s3.upload_file(test_file, r2_bucket, f'tests/{test_file}')
        print(f"Successfully uploaded {test_file} to R2.")
        
        # Try to download it back
        download_path = f'downloaded_{test_file}'
        s3.download_file(r2_bucket, f'tests/{test_file}', download_path)
        print(f"Successfully downloaded {test_file} from R2.")
        
        # Cleanup
        s3.delete_object(Bucket=r2_bucket, Key=f'tests/{test_file}')
        os.remove(test_file)
        os.remove(download_path)
        print("Cleanup successful.")
        
        return True
    except ClientError as e:
        print(f"AWS ClientError: {e}")
        return False
    except Exception as e:
        print(f"Unexpected error: {e}")
        return False

if __name__ == "__main__":
    if test_r2_connection():
        print("\nRESULT: R2 Connection Test PASSED")
        exit(0)
    else:
        print("\nRESULT: R2 Connection Test FAILED")
        exit(1)
