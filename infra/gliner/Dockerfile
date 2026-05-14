FROM python:3.12-slim

WORKDIR /app

# System dependencies for PyTorch
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

# Pre-download the model into the image layer (avoids runtime download)
# Override GLINER_MODEL_PATH at runtime to use a different model.
ARG GLINER_MODEL_PATH=urchade/gliner_large-v2.1
ENV GLINER_MODEL_PATH=${GLINER_MODEL_PATH}

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')"

# Security: run as non-root (F-009)
# Pre-create the HuggingFace cache directory with correct ownership so the named
# volume inherits appuser ownership on first mount (Docker copies image dir into
# a new empty volume, preserving permissions).
RUN useradd --create-home --uid 1001 appuser && \
    mkdir -p /home/appuser/.cache/huggingface && \
    chown -R appuser:appuser /home/appuser/.cache
USER appuser

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
