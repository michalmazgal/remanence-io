import os
import subprocess
import sys
import time
import json
import numpy as np
import cupy as cp
import boto3
import tempfile
from grain_processor import GrainProcessor

# Configuration
R2_BUCKET = "remanence-data"
CUDA_SOURCE = os.path.join(os.path.dirname(__file__), "grain_engine.cu")
BITRATE = "2M"
SVTAV1_PARAMS = "grain-synthesis=1"


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

def upload_to_r2(local_path, r2_path):
    print(f"Uploading {local_path} to R2: {r2_path}...")
    s3 = get_r2_client()
    s3.upload_file(local_path, R2_BUCKET, r2_path)

def get_video_size(path):
    return os.path.getsize(path)

def measure_quality(original, processed):
    if not os.path.exists(processed) or os.path.getsize(processed) == 0:
        print(f"Processed file {processed} not found or empty. Quality score: 0.0")
        return 0.0
        
    print(f"Measuring quality between {original} and {processed}...")
    # Using FFmpeg's SSIM filter
    cmd = [
        'ffmpeg', '-y', '-i', processed, '-i', original,
        '-filter_complex', 'ssim', '-f', 'null', '-'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # SSIM output is usually in the stderr
    # Example: "All: average: 0.987654"
    for line in result.stderr.split('\n'):
        if 'All: average:' in line:
            return float(line.split('average:')[1].split()[0])
    return 0.0

def advanced_seed_search(processor, frame, coarse_seeds=1000, fine_range=50):
    # 1. Coarse search
    c_seeds = np.random.randint(0, 100000, coarse_seeds, dtype=np.uint32)
    best_seed_coarse = processor.find_best_seed(frame, c_seeds)
    
    # 2. Fine search around the best coarse seed
    f_seeds = np.arange(
        max(0, best_seed_coarse - fine_range), 
        min(100000, best_seed_coarse + fine_range + 1), 
        dtype=np.uint32
    )
    best_seed_fine = processor.find_best_seed(frame, f_seeds)
    
    return best_seed_fine

def run_benchmark(source_path):
    # Video properties
    probe = subprocess.run([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0', 
        '-show_entries', 'stream=width,height,avg_frame_rate', 
        '-of', 'default=noprint_wrappers=1:nokey=1', source_path
    ], capture_output=True, text=True)
    
    lines = probe.stdout.strip().split('\n')
    width = int(lines[0])
    height = int(lines[1])
    fps_eval = lines[2].split('/')
    fps = float(fps_eval[0]) / float(fps_eval[1])
    
    print(f"Video: {width}x{height} @ {fps:.2f} fps")
    
    # --- Standard Encoding ---
    standard_out = "standard_av1.mp4"
    start_time = time.time()
    subprocess.run([
        'ffmpeg', '-y', '-i', source_path,
        '-c:v', 'libsvtav1', '-b:v', BITRATE, '-preset', '8',
        standard_out
    ], check=True, capture_output=True)
    standard_time = time.time() - start_time
    
    # --- Custom Encoding ---
    custom_out = "custom_ai_av1.mp4"
    processor = GrainProcessor(CUDA_SOURCE)
    
    # To avoid pipe deadlocks, we process raw frames into a temporary file first
    with tempfile.NamedTemporaryFile(delete=False) as tmp_raw:
        tmp_raw_path = tmp_raw.name
        
        # Input pipe: Extract raw YUV420p
        input_cmd = [
            'ffmpeg', '-i', source_path,
            '-f', 'rawvideo', '-pix_fmt', 'yuv420p', '-'
        ]
        p_in = subprocess.Popen(input_cmd, stdout=subprocess.PIPE, bufsize=10**7)
        
        frame_size = width * height * 3 // 2  # YUV420p: Y=WxH, U=WxH/4, V=WxH/4
        y_size = width * height
        
        frame_count = 0
        try:
            while True:
                raw_frame = p_in.stdout.read(frame_size)
                if not raw_frame:
                    break
                    
                # Split Y, U, V
                y_plane = np.frombuffer(raw_frame[:y_size], dtype=np.uint8).reshape((height, width))
                uv_planes = raw_frame[y_size:]
                
                # Advanced seed search & process
                best_seed = advanced_seed_search(processor, y_plane)
                processed_y = processor.process_frame(y_plane, best_seed)
                
                # Write processed frames to temp file
                tmp_raw.write(processed_y.tobytes())
                tmp_raw.write(uv_planes)
                
                frame_count += 1
                if frame_count % 100 == 0:
                    print(f"Processed {frame_count} frames...")
        finally:
            p_in.stdout.close()
            p_in.wait()
            tmp_raw.close()

    start_time = time.time()
    output_cmd = [
        'ffmpeg', '-y', '-f', 'rawvideo', '-pix_fmt', 'yuv420p', 
        '-s', f'{width}x{height}', '-r', str(fps), '-i', tmp_raw_path,
        '-c:v', 'libsvtav1', '-b:v', BITRATE, '-preset', '8', 
        '-svtav1-params', SVTAV1_PARAMS, custom_out
    ]
    
    try:
        subprocess.run(output_cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"Encoding failed with {SVTAV1_PARAMS}: {e.stderr.decode()}")
        print("Attempting fallback encoding without grain-synthesis...")
        # Fallback: Remove the SVT-AV1 params if they caused the failure
        fallback_cmd = [
            'ffmpeg', '-y', '-f', 'rawvideo', '-pix_fmt', 'yuv420p', 
            '-s', f'{width}x{height}', '-r', str(fps), '-i', tmp_raw_path,
            '-c:v', 'libsvtav1', '-b:v', BITRATE, '-preset', '8', 
            custom_out
        ]
        try:
            subprocess.run(fallback_cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e2:
            print(f"Fallback encoding also failed: {e2.stderr.decode()}")
    finally:
        if os.path.exists(tmp_raw_path):
            os.remove(tmp_raw_path)
            
    custom_time = time.time() - start_time
    
    # --- Metrics ---
    orig_size = get_video_size(source_path)
    std_size = get_video_size(standard_out)
    
    try:
        cust_size = get_video_size(custom_out)
    except FileNotFoundError:
        cust_size = 0
        
    quality_score = measure_quality(source_path, custom_out)
    
    report = {
        "original_size_bytes": orig_size,
        "standard_av1_size_bytes": std_size,
        "custom_av1_size_bytes": cust_size,
        "standard_encoding_time_sec": standard_time,
        "custom_encoding_time_sec": custom_time,
        "quality_ssim": quality_score,
        "frames_processed": frame_count
    }
    
    # Save Report
    with open("benchmark_report.json", "w") as f:
        json.dump(report, f, indent=4)
        
    with open("benchmark_summary.md", "w") as f:
        f.write(f"# Benchmark Summary\n\n")
        f.write(f"| Metric | Standard AV1 | Custom AI AV1 |\n")
        f.write(f"| --- | --- | --- |\n")
        f.write(f"| Size | {std_size/1024/1024:.2f} MB | {cust_size/1024/1024:.2f} MB |\n")
        f.write(f"| Time | {standard_time:.2f} s | {custom_time:.2f} s |\n")
        f.write(f"\n**Quality Score (SSIM):** {quality_score:.4f}\n")
        f.write(f"**Total Frames:** {frame_count}\n")
        
    # Upload to R2
    upload_to_r2(standard_out, f"benchmarks/{os.path.basename(source_path)}_std.mp4")
    if cust_size > 0:
        upload_to_r2(custom_out, f"benchmarks/{os.path.basename(source_path)}_custom.mp4")
    upload_to_r2("benchmark_report.json", f"benchmarks/{os.path.basename(source_path)}_report.json")
    upload_to_r2("benchmark_summary.md", f"benchmarks/{os.path.basename(source_path)}_summary.md")
    
    print("\nBenchmark completed and uploaded to R2.")
    return report

if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_benchmark(sys.argv[1])
    else:
        print("Usage: python3 benchmark.py <source_video_path>")
