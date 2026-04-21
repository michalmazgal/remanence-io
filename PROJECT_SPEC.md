# Remanence.io Service Specification

## Service Overview
AI-powered video compression to AV1 available at `www.remanence.io`.

## User Flow
1. Customer purchases storage.
2. Customer uploads video.
3. Server performs background conversion to AV1.
4. Result is stored in a new directory.
5. Both original and compressed videos are deleted after 7 days.
6. Payments handled via Stripe.

## Technical Know-How (Compression Pipeline)
1. **Grain Discovery**: Use GPU packages with ECC to find the generative AV1 grain for each frame.
2. **Optimization**: Identify the grain with the highest match per frame.
3. **Noise Removal**: Subtract the identified grain from the original video.
4. **Encoding**: Compress the noise-free video to AV1.
5. **Grain Synthesis**: Add the seed of the discovered grain to each frame's AV1 parameters to reconstruct grain during playback.

## Comparison Requirement
Provide two versions of the same video on Cloudflare R2 for customer comparison:
- Video A: Compressed using the Remanence.io method.
- Video B: Compressed using standard AV1 encoding.
