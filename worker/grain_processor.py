import cupy as cp
import numpy as np
import cv2

class GrainProcessor:
    def __init__(self, cuda_source_path):
        with open(cuda_source_path, 'r') as f:
            self.source = f.read()
        
        self.gen_kernel = cp.RawKernel(self.source, 'generate_grain_matrix_kernel')
        self.sub_kernel = cp.RawKernel(self.source, 'subtract_grain_kernel')

    def find_best_seed(self, frame, candidate_seeds):
        # GPU Normalization to FP16
        frame_gpu = cp.asarray(frame).astype(cp.float16) / 255.0
        v = frame_gpu.flatten()
        
        num_seeds = len(candidate_seeds)
        height, width = frame.shape[:2]
        num_pixels = width * height
        
        seeds_gpu = cp.asarray(candidate_seeds, dtype=cp.uint32)
        
        # Allocate Grain Matrix G (num_pixels, num_seeds)
        g_gpu = cp.zeros((num_pixels, num_seeds), dtype=cp.float16)
        
        # Generate G
        total_elements = num_pixels * num_seeds
        block_size = 256
        grid_size = (total_elements + block_size - 1) // block_size
        
        self.gen_kernel((grid_size,), (block_size,), 
                        (g_gpu, seeds_gpu, num_seeds, width, height))
        
        # Tensor Core Correlation: R = G^T * V
        # g_gpu.T is (num_seeds, num_pixels), v is (num_pixels,)
        # results is (num_seeds,)
        results_gpu = cp.dot(g_gpu.T, v)
        
        best_idx = cp.argmax(results_gpu)
        return int(candidate_seeds[int(best_idx)])

    def process_frame(self, frame, seed, strength=0.05):
        # GPU Normalization to FP16
        frame_gpu = cp.asarray(frame).astype(cp.float16) / 255.0
        
        height, width = frame.shape[:2]
        
        block_size = (16, 16)
        grid_size = ((width + 15) // 16, (height + 15) // 16)
        
        self.sub_kernel(grid_size, block_size, 
                        (frame_gpu, cp.uint32(seed), cp.float32(strength), width, height))
        
        result = cp.asnumpy(frame_gpu)
        return (np.clip(result, 0, 1) * 255).astype(np.uint8)

if __name__ == "__main__":
    processor = GrainProcessor('grain_engine.cu')
    dummy_frame = np.random.randint(0, 256, (1080, 1920), dtype=np.uint8)
    seeds = np.random.randint(0, 10000, 10, dtype=np.uint32)
    
    best_seed = processor.find_best_seed(dummy_frame, seeds)
    print(f"Best seed: {best_seed}")
    
    processed = processor.process_frame(dummy_frame, best_seed)
    print("Frame processed successfully")
