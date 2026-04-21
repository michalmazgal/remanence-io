import subprocess
import time
import os

def run_command(cmd):
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
    return result

def test_vast_cycle():
    # Load API key
    secrets = {}
    with open('/root/.heatsun_secrets', 'r') as f:
        for line in f:
            if '=' in line:
                k, v = line.strip().split('=', 1)
                secrets[k] = v
    
    api_key = secrets.get('VAST_API_KEY')
    os.environ['VAST_API_KEY'] = api_key

    print("Testing Vast.ai cycle: Search -> Create -> Destroy...")

    # 1. Search for any offer (no filters to ensure we find something for the test)
    search_cmd = ['vastai', 'search', 'offers']
    search_res = run_command(search_cmd)
    
    if search_res.returncode != 0 or not search_res.stdout:
        print("Failed to find any GPU offers.")
        return False
    
    lines = search_res.stdout.strip().split('\n')
    if len(lines) < 2:
        print("No offers found in search result.")
        return False
    
    offer_id = lines[1].split()[0]
    print(f"Picked offer: {offer_id}")

    # 2. Create instance
    create_cmd = ['vastai', 'create', 'instance', offer_id, '--image', 'nvidia/cuda:12.2.0-base-ubuntu22.04', '--raw']
    create_res = run_command(create_cmd)
    
    if create_res.returncode != 0:
        print("Failed to create instance.")
        return False
    
    try:
        import json
        data = json.loads(create_res.stdout)
        if 'id' in data:
            instance_id = data['id']
        elif 'instance_id' in data:
            instance_id = data['instance_id']
        elif 'new_contract' in data:
            instance_id = str(data['new_contract'])
        else:
            print(f"Could not find ID in JSON response: {data}")
            return False
        print(f"Instance created: {instance_id}")
        
        print("Waiting 30 seconds for instance to stabilize...")
        time.sleep(30)
        
        status_cmd = ['vastai', 'show', 'instances']
        status_res = run_command(status_cmd)
        if instance_id in status_res.stdout:
            print("Instance is confirmed as running.")
        else:
            print("Instance not found in running list.")
            
    finally:
        # 3. Destroy instance
        if 'instance_id' in locals():
            print(f"Destroying instance {instance_id}...")
            destroy_cmd = ['vastai', 'destroy', 'instance', instance_id]
            destroy_res = run_command(destroy_cmd)
            if destroy_res.returncode == 0:
                print("Instance destroyed successfully.")
            else:
                print("Failed to destroy instance!")
                return False

    return True

if __name__ == "__main__":
    if test_vast_cycle():
        print("\nRESULT: Vast.ai Cycle Test PASSED")
        exit(0)
    else:
        print("\nRESULT: Vast.ai Cycle Test FAILED")
        exit(1)
