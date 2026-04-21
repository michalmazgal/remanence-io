import os
import subprocess
import boto3
import time
import sys
import json
import signal

# Configuration
DEFAULT_TEMPLATE_HASH = 'eb2ab4cbd19599ce6d0af2df73423dc9'

def load_secrets():
    secrets = {}
    try:
        with open('/root/.heatsun_secrets', 'r') as f:
            for line in f:
                if '=' in line:
                    k, v = line.strip().split('=', 1)
                    secrets[k] = v
    except FileNotFoundError:
        pass
    return secrets

secrets = load_secrets()
R2_ACCESS_KEY = os.getenv('R2_ACCESS_KEY') or secrets.get('R2_ACCESS_KEY')
R2_SECRET_KEY = os.getenv('R2_SECRET_KEY') or secrets.get('R2_SECRET_KEY')
R2_BUCKET = os.getenv('R2_BUCKET') or secrets.get('R2_BUCKET')
R2_ENDPOINT = os.getenv('R2_ENDPOINT') or secrets.get('R2_ENDPOINT', 'https://your-endpoint.r2.cloudflarestorage.com')

if R2_ENDPOINT and '/heatsun-data' in R2_ENDPOINT:
    R2_ENDPOINT = R2_ENDPOINT.split('/heatsun-data')[0]

GH_USER = os.getenv('GH_USER') or secrets.get('GH_USER')
DOCKER_IMAGE = f"ghcr.io/{GH_USER}/remanence-worker:latest" if GH_USER else "ghcr.io/default/remanence-worker:latest"

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

def get_template_for_gpu(gpu_name):
    gpu_map = {
        'RTX_A6000': 'eb2ab4cbd19599ce6d0af2df73423dc9',
        'A100': 'eb2ab4cbd19599ce6d0af2df73423dc9',
        'H100': 'a74d9e369719273bca0ae861093e4d0c',
        'RTX_3090': 'eb2ab4cbd19599ce6d0af2df73423dc9', # Fallback
        'RTX_4090': 'eb2ab4cbd19599ce6d0af2df73423dc9'  # Fallback
    }
    for key, thash in gpu_map.items():
        if key in gpu_name:
            return thash
    return None

def orchestrate_video(video_name):
    global current_instance_id
    print(f"Starting orchestration for {video_name}")
    instance_id = None

    
    try:
        # 1. Find a high-end GPU
        print("Searching for available GPU offers...")
        search_cmd = [
            'vastai', 'search', 'offers', 
            'gpu_name=RTX_A6000,A100,H100,RTX_3090,RTX_4090',
            '--raw'
        ]
        search_res = run_command(search_cmd)
        
        # Fallback: if no high-end GPUs, search for ANY available GPU to ensure service availability
        if search_res.returncode != 0 or not search_res.stdout or search_res.stdout.strip() == '[]':
            print("No high-end GPUs available, searching for any available GPU...")
            search_cmd = ['vastai', 'search', 'offers', '--raw']
            search_res = run_command(search_cmd)

        if search_res.returncode != 0 or not search_res.stdout:
            print("No GPUs available in search results")
            return False
        
        try:
            offers_data = json.loads(search_res.stdout)
            offers = []
            for offer in offers_data:
                try:
                    offer_id = offer['id']
                    gpu_name = offer.get('gpu_name', '')
                    price = float(offer.get('price', float('inf')))
                    offers.append((price, offer_id, gpu_name))
                except (KeyError, ValueError):
                    continue
        except json.JSONDecodeError:
            print("Failed to parse search results as JSON")
            return False
        
        if not offers:
            print("No valid offers parsed from search output")
            return False

        offers.sort() # Sort by price ascending
        price, selected_offer, gpu_name = offers[0]
        selected_offer = str(selected_offer)
        print(f"Selected cheapest offer: {selected_offer} ({gpu_name}) at ${price}/hr")
                
        # 2. Determine template or image
        template_hash = get_template_for_gpu(gpu_name)
        if template_hash:
            print(f"Using template hash: {template_hash}")
            creation_arg = f'--template_hash={template_hash}'
        else:
            print(f"No specific template found for {gpu_name}, using default authenticated template: {DEFAULT_TEMPLATE_HASH}")
            creation_arg = f'--template_hash={DEFAULT_TEMPLATE_HASH}'
        
        # 3. Rent the instance
        print(f"Creating instance on offer {selected_offer}...")
        if '=' in creation_arg:
            create_cmd = [
                'vastai', 'create', 'instance', 
                selected_offer, 
                creation_arg, 
                '--env', f'R2_ACCESS_KEY={R2_ACCESS_KEY},R2_SECRET_KEY={R2_SECRET_KEY},R2_BUCKET={R2_BUCKET},R2_ENDPOINT={R2_ENDPOINT},VIDEO_NAME={video_name}',
                '--raw'
            ]
        else:
            # Handle --image DOCKER_IMAGE as two separate args
            arg_parts = creation_arg.split()
            create_cmd = [
                'vastai', 'create', 'instance', 
                selected_offer, 
                *arg_parts,
                '--env', f'R2_ACCESS_KEY={R2_ACCESS_KEY},R2_SECRET_KEY={R2_SECRET_KEY},R2_BUCKET={R2_BUCKET},R2_ENDPOINT={R2_ENDPOINT},VIDEO_NAME={video_name}',
                '--raw'
            ]
            
        create_res = run_command(create_cmd)
        if create_res.returncode != 0:
            print(f"Failed to create instance: {create_res.stderr}")
            return False
        
        try:
            create_data = json.loads(create_res.stdout)
            instance_id = create_data.get('id') or create_data.get('new_contract')
            current_instance_id = instance_id
            if not instance_id:
                raise ValueError("No instance ID found in JSON response")
            print(f"Instance created successfully: {instance_id}")

        except (json.JSONDecodeError, ValueError) as e:
            print(f"Could not parse instance ID from output: {create_res.stdout}. Error: {e}")
            return False
        
        # 4. Wait for report
        print(f"Waiting for benchmark report for {video_name}...")
        timeout = 2 * 60 * 60 # 2 hours
        start_time = time.time()
        while True:
            if time.time() - start_time > timeout:
                print(f"Timeout reached waiting for report for {video_name}. Aborting.")
                return False
            response = s3.list_objects_v2(Bucket=R2_BUCKET, Prefix=f'reports/{video_name}.txt')
            if 'Contents' in response:
                print(f"Benchmark report for {video_name} is ready")
                break
            print("Still processing benchmark...")
            time.sleep(60)
            
    except Exception as e:
        print(f"An error occurred during orchestration: {e}")
        return False
    finally:
        if instance_id:
            instance_id_str = str(instance_id)
            print(f"Destroying instance {instance_id_str}...")
            destroy_cmd = ['vastai', 'destroy', 'instance', instance_id_str]
            run_command(destroy_cmd)
    
    return True

def main():
    # Global instance tracking for signal handling
    global current_instance_id
    current_instance_id = None

    def signal_handler(sig, frame):
        print(f"\nReceived signal {sig}. Cleaning up...")
        if current_instance_id:
            instance_id_str = str(current_instance_id)
            print(f"Destroying emergency instance {instance_id_str}...")
            subprocess.run(['vastai', 'destroy', 'instance', instance_id_str])
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

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
