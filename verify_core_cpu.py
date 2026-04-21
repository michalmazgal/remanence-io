import numpy as np

def jump_lcg(seed, n):
    """
    Implements the LCG jump logic to find the n-th state of the PRNG.
    X_n = (a^n * seed + c * (a^n - 1) / (a - 1)) mod 2^32
    """
    a = 1664525
    c = 1013904223
    cur_a = a
    cur_c = c
    res_a = 1
    res_c = 0
    n_val = n
    while n_val > 0:
        if n_val & 1:
            res_a = (res_a * cur_a) & 0xFFFFFFFF
            res_c = (res_c * cur_a + cur_c) & 0xFFFFFFFF
        cur_c = (cur_c * cur_a + cur_c) & 0xFFFFFFFF
        cur_a = (cur_a * cur_a) & 0xFFFFFFFF
        n_val >>= 1
    return (res_a * seed + res_c) & 0xFFFFFFFF

def get_grain_sequence(seed, num_pixels):
    """
    Generates the grain sequence for a given seed and number of pixels.
    Follows the logic: sample(seed, n) uses jump_lcg(seed, n+1).
    """
    samples = np.zeros(num_pixels, dtype=np.float32)
    
    # Start at the first sample (n=0), which is jump_lcg(seed, 1)
    state = jump_lcg(seed, 1)
    a = 1664525
    c = 1013904223
    
    for n in range(num_pixels):
        val = (state >> 16) & 0x3FFF
        samples[n] = (val / 8191.5) - 1.0
        state = (state * a + c) & 0xFFFFFFFF
        
    return samples

def find_best_seed(frame, candidate_seeds):
    """
    Finds the seed among candidates that has the highest correlation with the frame.
    """
    v = frame.flatten()
    best_seed = None
    max_corr = -float('inf')
    
    for seed in candidate_seeds:
        grain = get_grain_sequence(seed, len(v))
        corr = np.dot(grain, v)
        if corr > max_corr:
            max_corr = corr
            best_seed = seed
    return best_seed

def subtract_grain(frame, seed, strength):
    """
    Subtracts grain from the frame using the specified seed and strength.
    """
    height, width = frame.shape
    num_pixels = width * height
    grain = get_grain_sequence(seed, num_pixels).reshape(height, width)
    
    result = frame - grain * strength
    return np.clip(result, 0, 1)

def add_grain(frame, seed, strength):
    """
    Adds grain to a frame for testing purposes.
    """
    height, width = frame.shape
    num_pixels = width * height
    grain = get_grain_sequence(seed, num_pixels).reshape(height, width)
    
    result = frame + grain * strength
    return np.clip(result, 0, 1)

def run_verification():
    print("Starting Verification...")
    
    # 1. Generate synthetic 1080p grayscale frame [0, 1]
    np.random.seed(0)
    original_frame = np.random.uniform(0.2, 0.8, (1080, 1920)).astype(np.float32)
    
    # 2. Add grain from a known seed (seed=42) with a specific strength
    true_seed = 42
    strength = 0.1
    grainy_frame = add_grain(original_frame, true_seed, strength)
    print(f"Added grain with seed {true_seed} and strength {strength}")
    
    # 3. Use find_best_seed to recover the seed
    candidate_seeds = [10, 20, 30, 42, 50, 60, 70, 80, 90, 100]
    recovered_seed = find_best_seed(grainy_frame, candidate_seeds)
    print(f"Recovered seed: {recovered_seed}")
    
    if recovered_seed == true_seed:
        print("SUCCESS: Seed recovered correctly.")
    else:
        print(f"FAILURE: Seed recovery failed. Expected {true_seed}, got {recovered_seed}")
        return False
    
    # 4. Use subtract_grain and verify it's close to original
    denoised_frame = subtract_grain(grainy_frame, true_seed, strength)
    mse = np.mean((original_frame - denoised_frame)**2)
    print(f"Mean Squared Error between original and denoised: {mse:.6f}")
    
    if mse < 1e-5:
        print("SUCCESS: Frame denoised successfully.")
    else:
        print(f"FAILURE: Denoising failed. MSE too high: {mse:.6f}")
        return False
        
    return True

if __name__ == "__main__":
    if run_verification():
        print("\nOverall Result: PASSED")
    else:
        print("\nOverall Result: FAILED")
        exit(1)
