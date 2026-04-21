FROM nvidia/cuda:12.2.0-base-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    ffmpeg \
    libopencv-dev \
    wget \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY worker/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt boto3 cupy-cuda12x opencv-python-headless

COPY worker/ ./worker/

CMD ["python3", "/app/worker/worker_entrypoint.py"]
