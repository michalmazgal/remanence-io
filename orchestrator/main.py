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
        'H100': 'h100',
        'RTX_3090': 'ada6000', # Fallback for testing
        'RTX_4090': 'ada6000'  # Fallback for testing
    }
    for key, tag in gpu_map.items():
        if key in gpu_name:
            return f"ghcr.io/{os.getenv('GH_USER')}/remanence-worker-{tag}:latest"
    return None

def orchestrate_video(video_name):
    print(f"Starting orchestration for {video_name}")
    
    # 1. Find a high-end GPU (Expanding for immediate test)
    # Removed sort_by and limit as they are not supported by this CLI version
    search_cmd = [
        'vastai', 'search', 'offers', 
        'gpu_name=RTX_A6000,A100,H100,RTX_3090,RTX_4090'
    ]
    search_res = run_command(search_cmd)
    if search_res.returncode != 0 or not search_res.stdout:
        print("No suitable GPUs available")
        return False
    
    lines = search_res.stdout.strip().split('\n')
    if len(lines) < 2:
        print("Could not find offers")
        return False

    # We'll handle sorting by price in Python
    offers = []
    for line in lines[1:]:
        parts = line.split()
        if not parts: continue
        try:
            offer_id = parts[0]
            gpu_name = parts[4] if len(parts) > 4 else "" # Adjusted index for the actual CLI output
            price = float(parts[9]) if len(parts) > 9 else float('inf')
            offers.append((price, offer_id, gpu_name))
        except (ValueError, IndexError):
            continue
    
    offers.sort() # Sort by price ascending
            
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
            response = s3.list_objects_v2(Bucket=R2_BUCKET, Prefix=f'reports/{video_name}.txt')
            if 'Contents' in response:
                print(f"Benchmark report for {video_name} is ready")
                break
            print("Still processing benchmark...")
            time.sleep(60)
    finally:
        destroy_cmd = ['vastai', 'destroy', 'instance', instance_id]
        run_command(destroy_cmd)
    
    return True

def main():
    while True:
        videos = list_pending_videos()
        if not videos:
            print("No pending videos to process. Waiting 5 minutes...")
            time.sleep(300)
            continue
        
        for video in videos:
            success = orchestrate_video(video)
            if success:
                print(f"Successfully processed {video}")
            else:
                print(f"Failed to process {video}, will retry in the next cycle")
        
        print("Cycle complete. Sleeping 60 seconds before next check...")
        time.sleep(60)

if __name__ == "__main__":
    main()
