import os
import subprocess
import boto3
import cv2
import numpy as np
import sys
from grain_processor import GrainProcessor
from benchmark import run_benchmark

# Configuration from environment variables
R2_ACCESS_KEY = os.getenv('R2_ACCESS_KEY')
R2_SECRET_KEY = os.getenv('R2_SECRET_KEY')
R2_BUCKET = os.getenv('R2_BUCKET')
R2_ENDPOINT = os.getenv('R2_ENDPOINT', 'https://your-endpoint.r2.cloudflarestorage.com')
VIDEO_NAME = os.getenv('VIDEO_NAME')
RUN_BENCHMARK = os.getenv('RUN_BENCHMARK', 'false').lower() == 'true'

# Configuration from environment variables
R2_ACCESS_KEY = os.getenv('R2_ACCESS_KEY')
R2_SECRET_KEY = os.getenv('R2_SECRET_KEY')
R2_BUCKET = os.getenv('R2_BUCKET')
R2_ENDPOINT = os.getenv('R2_ENDPOINT', 'https://your-endpoint.r2.cloudflarestorage.com')
VIDEO_NAME = os.getenv('VIDEO_NAME')

s3 = boto3.client(
    's3',
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
    endpoint_url=R2_ENDPOINT
)

def download_video(video_name):
    local_path = f"/tmp/{os.path.basename(video_name)}"
    print(f"Downloading {video_name}...")
    s3.download_file(R2_BUCKET, video_name, local_path)
    return local_path

def upload_video(local_path, video_name):
    output_name = f"processed/{video_name}"
    print(f"Uploading {output_name}...")
    s3.upload_file(local_path, R2_BUCKET, output_name)

def find_best_seed(video_path):
    # Extract one frame at 1 second
    frame_path = "/tmp/sample_frame.png"
    subprocess.run([
        'ffmpeg', '-i', video_path, '-ss', '00:00:01', '-vframes', '1', '-q:v', '2', frame_path
    ], check=True, capture_output=True)
    
    frame = cv2.imread(frame_path, cv2.IMREAD_GRAYSCALE)
    if frame is None:
        raise RuntimeError("Could not extract frame")
    
    processor = GrainProcessor('worker/grain_engine.cu')
    seeds = np.random.randint(0, 10000, 100, dtype=np.uint32)
    best_seed = processor.find_best_seed(frame, seeds)
    print(f"Best seed found: {best_seed}")
    return best_seed

import time

def standard_encode(video_path):
    output_path = f"/tmp/standard_{os.path.basename(video_path)}"
    start_time = time.time()
    
    encode_cmd = [
        'ffmpeg', '-y', '-i', video_path, 
        '-c:v', 'libsvtav1', '-preset', '8', '-crf', '30', 
        output_path
    ]
    
    subprocess.run(encode_cmd, check=True, capture_output=True)
    end_time = time.time()
    
    return output_path, end_time - start_time

def process_and_encode(video_path, seed):
    output_path = f"/tmp/optimized_{os.path.basename(video_path)}"
    start_time = time.time()
    
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', 
                           '-show_entries', 'stream=width,height', '-of', 'csv=p=0', video_path], 
                          capture_output=True, text=True)
    width, height = map(int, probe.stdout.strip().split(','))
    
    extract_cmd = ['ffmpeg', '-i', video_path, '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1']
    encode_cmd = [
        'ffmpeg', '-y', '-f', 'rawvideo', '-pix_fmt', 'gray', '-s', f'{width}x{height}', '-i', 'pipe:0',
        '-c:v', 'libsvtav1', '-preset', '8', '-crf', '30', 
        '-svtav1-params', f'grain-synthesis=1:grain-seed={seed}',
        output_path
    ]
    
    p_extract = subprocess.Popen(extract_cmd, stdout=subprocess.PIPE, bufsize=10**8)
    p_encode = subprocess.Popen(encode_cmd, stdin=subprocess.PIPE, bufsize=10**8)
    
    processor = GrainProcessor('worker/grain_engine.cu')
    frame_size = width * height
    
    try:
        while True:
            raw_frame = p_extract.stdout.read(frame_size)
            if not raw_frame: break
            frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape((height, width))
            processed_frame = processor.process_frame(frame, seed)
            p_encode.stdin.write(processed_frame.tobytes())
    finally:
        p_extract.stdout.close()
        p_encode.stdin.close()
        p_extract.wait()
        p_encode.wait()
        
    end_time = time.time()
    return output_path, end_time - start_time

def main():
    if not VIDEO_NAME:
        print("VIDEO_NAME environment variable not set")
        sys.exit(1)
        
    try:
        if RUN_BENCHMARK:
            print(f"Running full benchmark for {VIDEO_NAME}...")
            # Download video to local path for benchmark.py
            local_path = f"/tmp/{os.path.basename(VIDEO_NAME)}"
            s3 = boto3.client(
                's3',
                aws_access_key_id=R2_ACCESS_KEY,
                aws_secret_access_key=R2_SECRET_KEY,
                endpoint_url=R2_ENDPOINT
            )
            s3.download_file(R2_BUCKET, VIDEO_NAME, local_path)
            
            # Run the professional benchmark
            run_benchmark(local_path)
            print("Benchmark completed successfully")
            return

        video_path = download_video(VIDEO_NAME)
        
        # 1. Optimized Pipeline
        seed = find_best_seed(video_path)
        opt_path, opt_time = process_and_encode(video_path, seed)
        opt_size = os.path.getsize(opt_path)
        upload_video(opt_path, f"optimized/{VIDEO_NAME}")
        
        # 2. Standard Pipeline
        std_path, std_time = standard_encode(video_path)
        std_size = os.path.getsize(std_path)
        upload_video(std_path, f"standard/{VIDEO_NAME}")
        
        # 3. Comparison Report
        report = (
            f"Video: {VIDEO_NAME}\n"
            f"--- Optimized Pipeline ---\n"
            f"Time: {opt_time:.2f}s\n"
            f"Size: {opt_size / 1024 / 1024:.2f} MB\n"
            f"Seed: {seed}\n\n"
            f"--- Standard Pipeline ---\n"
            f"Time: {std_time:.2f}s\n"
            f"Size: {std_size / 1024 / 1024:.2f} MB\n"
        )
        report_path = f"/tmp/report_{VIDEO_NAME}.txt"
        with open(report_path, 'w') as f:
            f.write(report)
        s3.upload_file(report_path, R2_BUCKET, f"reports/{VIDEO_NAME}.txt")
        
        print("Benchmark completed successfully")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
