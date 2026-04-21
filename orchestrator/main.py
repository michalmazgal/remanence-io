import os
import subprocess
import boto3
import time
import sys

# Configuration
R2_ACCESS_KEY = os.getenv('R2_ACCESS_KEY')
R2_SECRET_KEY = os.getenv('R2_SECRET_KEY')
R2_BUCKET = os.getenv('R2_BUCKET')
R2_ENDPOINT = os.getenv('R2_ENDPOINT', 'https://your-endpoint.r2.cloudflarestorage.com')
DOCKER_IMAGE = f"ghcr.io/{os.getenv('GH_USER')}/remanence-worker:latest"

s3 = boto3.client(
    's3',
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
    endpoint_url=R2_ENDPOINT
)

def list_pending_videos():
    response = s3.list_objects_v2(Bucket=R2_BUCKET, Prefix='pending/')
    if 'Contents' not in response:
        return []
    return [obj['Key'].replace('pending/', '') for obj in response['Contents'] if obj['Key'] != 'pending/']

def run_command(cmd):
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
    return result

def orchestrate_video(video_name):
    print(f"Starting orchestration for {video_name}")
    
    # 1. Find an ADA6000 GPU
    # Search for ADA6000, sort by price
    search_cmd = [
        'vastai', 'search', 'offers', 
        'gpu_name=RTX_A6000', 
        'sort_by=price', 
        'limit=1'
    ]
    search_res = run_command(search_cmd)
    if search_res.returncode != 0 or not search_res.stdout:
        print("No ADA6000 GPUs available")
        return False
    
    # Extract offer ID
    lines = search_res.stdout.strip().split('\n')
    if len(lines) < 2:
        print("Could not find offer ID")
        return False
    offer_id = lines[1].split()[0]
    
    # 2. Rent the instance
    create_cmd = [
        'vastai', 'create', 'instance', 
        f'offer={offer_id}', 
        f'image={DOCKER_IMAGE}',
        f'env=R2_ACCESS_KEY={R2_ACCESS_KEY},R2_SECRET_KEY={R2_SECRET_KEY},R2_BUCKET={R2_BUCKET},R2_ENDPOINT={R2_ENDPOINT},VIDEO_NAME={video_name}'
    ]
    create_res = run_command(create_cmd)
    if create_res.returncode != 0:
        print("Failed to create instance")
        return False
    
    # Extract instance ID
    # vastai create instance output is usually something like "Instance 123456 created"
    instance_id = create_res.stdout.strip().split()[1]
    
    try:
        # 3. Monitor completion
        # We can monitor the instance status or check logs.
        # For simplicity, we'll poll the instance state.
        # When the worker finishes, it can simply exit, but the instance remains.
        # A better way is to check the logs for "Processing completed successfully".
        
        while True:
            log_cmd = ['vastai', 'show', 'instances', instance_id, '-y'] # -y for yaml or just get output
            log_res = run_command(log_cmd)
            
            # In a real scenario, we would use 'vastai log' to check the worker's output
            # Or we could have the worker update a status file in R2.
            # Let's check if the video now exists in the 'processed/' folder.
            
            response = s3.list_objects_v2(Bucket=R2_BUCKET, Prefix=f'processed/{video_name}')
            if 'Contents' in response:
                print(f"Video {video_name} processed and uploaded")
                break
            
            print("Still processing...")
            time.sleep(60)
            
    finally:
        # 4. Destroy the instance
        destroy_cmd = ['vastai', 'destroy', 'instance', instance_id]
        run_command(destroy_cmd)
    
    return True

def main():
    videos = list_pending_videos()
    if not videos:
        print("No pending videos to process")
        return
    
    for video in videos:
        success = orchestrate_video(video)
        if not success:
            print(f"Failed to process {video}")

if __name__ == "__main__":
    main()
