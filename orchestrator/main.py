import os
import subprocess
import boto3
import time
import sys

# Configuration
R2_ACCESS_KEY = os.getenv('R2_ACCESS_KEY')
R2_SECRET_KEY = os.getenv('R2_SECRET_KEY')
R2_BUCKET = os.getenv('R2_BUCKET')
R2_ENDPOINT = os.getenv('R2_ENDPOINT', 'https://your-endpoint.r2.cloudflarestorage.com').split('/heatsun-data')[0] if '/heatsun-data' in os.getenv('R2_ENDPOINT', '') else os.getenv('R2_ENDPOINT', 'https://your-endpoint.r2.cloudflarestorage.com')
# Actually, simpler: just take the part before the first slash after the domain.
# Let's just use a clean way to handle it.

DOCKER_IMAGE = f"ghcr.io/{os.getenv('GH_USER')}/remanence-worker:latest"

s3 = boto3.client(
    's3',
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
    endpoint_url=R2_ENDPOINT
)

def list_pending_videos():
    response = s3.list_objects_v2(Bucket=R2_BUCKET)
    if 'Contents' not in response:
        return []
    return [obj['Key'] for obj in response['Contents'] if obj['Key'].endswith('.mp4') and not obj['Key'].startswith('processed/')]

def run_command(cmd):
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
    return result

def get_image_for_gpu(gpu_name):
    gpu_map = {
        'RTX_A6000': 'ada6000',
        'A100': 'a100',
        'H100': 'h100'
    }
    # Find a match in the map
    for key, tag in gpu_map.items():
        if key in gpu_name:
            return f"ghcr.io/{os.getenv('GH_USER')}/remanence-worker-{tag}:latest"
    return None

def orchestrate_video(video_name):
    print(f"Starting orchestration for {video_name}")
    
    # 1. Find an ECC GPU (A6000, A100, H100)
    # Search for compatible GPUs, sort by price
    search_cmd = [
        'vastai', 'search', 'offers', 
        'gpu_name=RTX_A6000,A100,H100', 
        'sort_by=price', 
        'limit=5'
    ]
    search_res = run_command(search_cmd)
    if search_res.returncode != 0 or not search_res.stdout:
        print("No compatible ECC GPUs available")
        return False
    
    lines = search_res.stdout.strip().split('\n')
    if len(lines) < 2:
        print("Could not find offers")
        return False

    # Try to find a GPU that has a matching image
    selected_offer = None
    selected_image = None
    
    for line in lines[1:]:
        parts = line.split()
        if not parts: continue
        offer_id = parts[0]
        gpu_name = parts[2] if len(parts) > 2 else ""
        
        image = get_image_for_gpu(gpu_name)
        if image:
            selected_offer = offer_id
            selected_image = image
            break
            
    if not selected_offer:
        print("No GPUs available with a corresponding Docker image")
        return False
    
    # 2. Rent the instance
    create_cmd = [
        'vastai', 'create', 'instance', 
        f'offer={selected_offer}', 
        f'image={selected_image}',
        f'env=R2_ACCESS_KEY={R2_ACCESS_KEY},R2_SECRET_KEY={R2_SECRET_KEY},R2_BUCKET={R2_BUCKET},R2_ENDPOINT={R2_ENDPOINT},VIDEO_NAME={video_name}'
    ]
    create_res = run_command(create_cmd)
    if create_res.returncode != 0:
        print("Failed to create instance")
        return False
    
    instance_id = create_res.stdout.strip().split()[1]
    
    try:
        while True:
            response = s3.list_objects_v2(Bucket=R2_BUCKET, Prefix=f'processed/{video_name}')
            if 'Contents' in response:
                print(f"Video {video_name} processed and uploaded")
                break
            print("Still processing...")
            time.sleep(60)
    finally:
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
