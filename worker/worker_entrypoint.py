import os
import subprocess
import boto3
import cv2
import numpy as np
import sys
from grain_processor import GrainProcessor

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

def process_and_encode(video_path, seed):
    output_path = f"/tmp/processed_{os.path.basename(video_path)}"
    
    # We use ffmpeg to pipe frames to python for grain subtraction, 
    # then pipe back to ffmpeg for SVT-AV1 encoding.
    # This is a simplified version. In a real scenario, we'd use a more robust pipe.
    
    # Grain subtraction via a separate script or integrated in this one.
    # For simplicity, let's implement a frame-by-frame processor.
    
    # We will run a subprocess that reads raw frames from ffmpeg,
    # processes them with GrainProcessor, and writes them back to ffmpeg.
    
    # Command to extract raw frames
    extract_cmd = [
        'ffmpeg', '-i', video_path, '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1'
    ]
    
    # Command to encode raw frames to AV1
    # We'll use SVT-AV1 through ffmpeg. 
    # grain_synthesis=1 enables grain synthesis in SVT-AV1.
    encode_cmd = [
        'ffmpeg', '-f', 'rawvideo', '-pix_fmt', 'gray', '-s', '1920x1080', '-i', 'pipe:0',
        '-c:v', 'libsvtav1', '-preset', '8', '-crf', '30', 
        '-svtav1-params', f'grain-synthesis=1:grain-seed={seed}',
        output_path
    ]
    
    # Since we need to process each frame with GrainProcessor, we can't just pipe ffmpeg to ffmpeg.
    # We'll use a python loop to read from one process and write to another.
    
    # First, get video dimensions
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', 
                           '-show_entries', 'stream=width,height', '-of', 'csv=p=0', video_path], 
                          capture_output=True, text=True)
    width, height = map(int, probe.stdout.strip().split(','))
    
    p_extract = subprocess.Popen(extract_cmd, stdout=subprocess.PIPE, bufsize=10**8)
    p_encode = subprocess.Popen(encode_cmd, stdin=subprocess.PIPE, bufsize=10**8)
    
    processor = GrainProcessor('worker/grain_engine.cu')
    frame_size = width * height
    
    try:
        while True:
            raw_frame = p_extract.stdout.read(frame_size)
            if not raw_frame:
                break
            
            frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape((height, width))
            processed_frame = processor.process_frame(frame, seed)
            p_encode.stdin.write(processed_frame.tobytes())
            
    finally:
        p_extract.stdout.close()
        p_encode.stdin.close()
        p_extract.wait()
        p_encode.wait()
        
    return output_path

def main():
    if not VIDEO_NAME:
        print("VIDEO_NAME environment variable not set")
        sys.exit(1)
        
    try:
        video_path = download_video(VIDEO_NAME)
        seed = find_best_seed(video_path)
        processed_path = process_and_encode(video_path, seed)
        upload_video(processed_path, VIDEO_NAME)
        print("Processing completed successfully")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
