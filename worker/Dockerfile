FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/workspace/hf
ENV OLLAMA_HOST=127.0.0.1:11434

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    git \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Ollama (binds to 127.0.0.1 only)
RUN curl -fsSL https://ollama.com/install.sh | sh

WORKDIR /workspace/worker

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x onstart.sh

EXPOSE 8000

CMD ["/bin/bash", "onstart.sh"]
