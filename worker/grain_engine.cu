extern "C" {

__device__ uint32_t jump_lcg(uint32_t seed, uint32_t n) {
    uint32_t a = 1664525;
    uint32_t c = 1013904223;
    uint32_t cur_a = a;
    uint32_t cur_c = c;
    uint32_t res_a = 1;
    uint32_t res_c = 0;
    while (n > 0) {
        if (n & 1) {
            res_a *= cur_a;
            res_c = res_c * cur_a + cur_c;
        }
        cur_c = cur_c * cur_a + cur_c;
        cur_a *= cur_a;
        n >>= 1;
    }
    return res_a * seed + res_c;
}

__device__ float av1_grain_sample(uint32_t seed, uint32_t n) {
    uint32_t state = jump_lcg(seed, n + 1);
    uint32_t val = (state >> 16) & 0x3FFF;
    return ((float)val / 8191.5f) - 1.0f;
}

__global__ void generate_grain_matrix_kernel(half* G, const uint32_t* seeds, int num_seeds, int width, int height) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    int num_pixels = width * height;
    int total_elements = num_pixels * num_seeds;
    if (tid >= total_elements) return;

    int pixel_idx = tid / num_seeds;
    int seed_idx = tid % num_seeds;
    
    if (seed_idx < num_seeds) {
        G[tid] = __float2half(av1_grain_sample(seeds[seed_idx], pixel_idx));
    }
}

__global__ void subtract_grain_kernel(half* frame, uint32_t seed, float strength, int width, int height) {
    int x = blockIdx.x * blockDim.x + threadIdx.x;
    int y = blockIdx.y * blockDim.y + threadIdx.y;

    if (x < width && y < height) {
        int idx = y * width + x;
        float grain = av1_grain_sample(seed, idx);
        float val = __half2float(frame[idx]) - grain * strength;
        
        if (val < 0.0f) val = 0.0f;
        if (val > 1.0f) val = 1.0f;
        frame[idx] = __float2half(val);
    }
}

}
