FROM ghcr.io/hydra-db/hydradb:0.4.0

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-venv curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x /app/start.sh && mkdir -p /data && chown -R 10001:10001 /data /app

USER 10001:10001
ENV PATH="/opt/venv/bin:$PATH"
EXPOSE 8080
ENTRYPOINT ["/app/start.sh"]
