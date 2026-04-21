import os
import subprocess
import cv2
import numpy as np
import cupy as cp
import boto3
from grain_processor import GrainProcessor

# Configuration
R2_BUCKET = "remanence-data"
CANDIDATE_SEEDS = np.random.randint(0, 10000, 20, dtype=np.uint32)
BITRATE = "2M"
SVTAV1_PARAMS = "grain=1"
CUDA_SOURCE = "grain_engine.cu"

def get_r2_client():
    secrets_path = os.path.expanduser("~/.heatsun_secrets")
    if not os.path.exists(secrets_path):
        raise FileNotFoundError(f"Secrets file not found at {secrets_path}")
        
    secrets = {}
    with open(secrets_path) as f:
        for line in f:
            if '=' in line:
                k, v = line.replace('export ', '').strip().split('=', 1)
                secrets[k] = v.strip('"').strip("'")
    
    return boto3.client('s3', 
                        endpoint_url=secrets['R2_ENDPOINT'], 
                        aws_access_key_id=secrets['R2_ACCESS_KEY'], 
                        aws_secret_access_key=secrets['R2_SECRET_KEY'])

def download_video(r2_path, local_path):
    print(f"Downloading {r2_path} from R2...")
    s3 = get_r2_client()
    s3.download_file(R2_BUCKET, r2_path, local_path)

def encode_standard(input_path, output_path):
    print(f"Encoding baseline: {output_path}")
    cmd = [
        'ffmpeg', '-y', '-i', input_path,
        '-c:v', 'libsvtav1', '-b:v', BITRATE,
        '-preset', '8', output_path
    ]
    subprocess.run(cmd, check=True)

def encode_custom(input_path, output_path):
    print(f"Encoding custom AI video: {output_path}")
    # Note: per-frame seed synthesis is not directly supported via ffmpeg CLI.
    # We enable grain synthesis globally as the best approximation.
    cmd = [
        'ffmpeg', '-y', '-i', input_path,
        '-c:v', 'libsvtav1', '-b:v', BITRATE,
        '-preset', '8', '-svtav1-params', SVTAV1_PARAMS,
        output_path
    ]
    subprocess.run(cmd, check=True)

def process_video(input_path, output_frames_dir):
    print("Processing frames to remove grain...")
    os.makedirs(output_frames_dir, exist_ok=True)
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise IOError(f"Could not open video {input_path}")
        
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    processor = GrainProcessor(CUDA_SOURCE)
    
    frame_idx = 0
    seeds_log = []
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        # Convert to YUV to process only the luminance channel
        yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV)
        y, u, v = cv2.split(yuv)
        
        # Find best seed based on Y channel
        best_seed = processor.find_best_seed(y, CANDIDATE_SEEDS)
        seeds_log.append(best_seed)
        
        # Process Y channel to remove grain
        processed_y = processor.process_frame(y, best_seed)
        
        # Reconstruct BGR frame
        merged_yuv = cv2.merge([processed_y, u, v])
        processed_frame = cv2.cvtColor(merged_yuv, cv2.COLOR_YUV2BGR)
        
        cv2.imwrite(os.path.join(output_frames_dir, f"frame_{frame_idx:05d}.png"), processed_frame)
        frame_idx += 1
        
        if frame_idx % 100 == 0:
            print(f"Processed {frame_idx} frames...")
            
    cap.release()
    return seeds_log, fps

def main(r2_video_path):
    local_source = "source_video.mp4"
    try:
        download_video(r2_video_path, local_source)
    except Exception as e:
        print(f"Failed to download from R2: {e}. Using local dummy if available.")
        if not os.path.exists(local_source):
            print("No local source_video.mp4 found. Please provide a valid R2 path.")
            return

    # 1. Baseline
    encode_standard(local_source, "standard_av1.mp4")
    
    # 2. Custom Pipeline
    frames_dir = "processed_frames"
    seeds, fps = process_video(local_source, frames_dir)
    
    # Encode processed frames to custom_ai_av1.mp4
    # Using -framerate to maintain original speed
    cmd = [
        'ffmpeg', '-y', '-framerate', str(fps), '-i', os.path.join(frames_dir, "frame_%05d.png"),
        '-c:v', 'libsvtav1', '-b:v', BITRATE,
        '-preset', '8', '-svtav1-params', SVTAV1_PARAMS,
        "custom_ai_av1.mp4"
    ]
    subprocess.run(cmd, check=True)
    
    print("\nComparison complete!")
    print(f"Baseline: standard_av1.mp4")
    print(f"Custom AI: custom_ai_av1.mp4")
    print(f"Total frames processed: {len(seeds)}")
    print(f"Average seed used: {np.mean(seeds):.2f}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        print("Usage: python3 comparison_gen.py <r2_video_path>")
        # For testing purposes, we can use a dummy path
        # main("test_video.mp4")
