# OhBot Behaviors Engine — Python control server
# Build:  docker compose build
# Run:    docker compose up
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Runtime libs + build tools (miniaudio / sounddevice need a C++ toolchain)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libportaudio2 \
        portaudio19-dev \
        espeak-ng \
        ca-certificates \
        build-essential \
        g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching)
COPY requirements/ requirements/
COPY pyproject.toml README.md ./
COPY src/ src/
COPY system_prompt.txt example_script.txt config.example.json ./

RUN pip install --upgrade pip \
    && pip install -e . \
    && pip install -r requirements/linux.txt \
    && apt-get update \
    && apt-get purge -y --auto-remove build-essential g++ portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Persist downloaded TTS models / user config via volumes
RUN mkdir -p /app/ohbotData \
    && cp config.example.json config.json

EXPOSE 8765

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "obot", "--serve", "--host", "0.0.0.0", "--port", "8765"]
