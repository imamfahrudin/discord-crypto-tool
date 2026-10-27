FROM python:3.9-slim

WORKDIR /app

# Install dependencies for Cloudflare WARP and DNS utilities
RUN apt-get update && apt-get install -y curl lsb-release gnupg procps && \
    curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | gpg --dearmor | tee /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg > /dev/null && \
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" | tee /etc/apt/sources.list.d/cloudflare-client.list && \
    apt-get update && apt-get install -y cloudflare-warp dnsutils && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Set timezone to Asia/Jakarta (WIB)
ENV TZ=Asia/Jakarta
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create persistence directories
RUN mkdir -p /app/data /app/cache

# Copy application source code
COPY . .

# Startup script handling optional WARP daemon and launching bot
RUN echo '#!/bin/bash\n\
if [ "$USE_WARP" = "true" ]; then\n\
    echo "Starting WARP daemon..."\n\
    warp-svc >/var/log/warp-svc.log 2>&1 &\n\
    echo "Waiting for WARP daemon to initialize..."\n\
    for i in {1..30}; do\n\
        if [ -S /run/cloudflare-warp/warp_service ]; then\n\
            echo "✅ Daemon ready after $i seconds"\n\
            break\n\
        fi\n\
        sleep 1\n\
    done\n\
    if [ ! -S /run/cloudflare-warp/warp_service ]; then\n\
        echo "❌ WARP daemon socket not found, proceeding without WARP"\n\
    else\n\
        echo "Registering WARP client..."\n\
        echo "y" | script -q -c "warp-cli registration new" /dev/null || echo "Registration existed"\n\
        sleep 2\n\
        echo "Setting WARP mode to warp+doh..."\n\
        warp-cli mode warp+doh\n\
        sleep 2\n\
        echo "Connecting WARP..."\n\
        warp-cli connect\n\
        sleep 6\n\
        STATUS=$(warp-cli status 2>&1)\n\
        echo "WARP status: $STATUS"\n\
    fi\n\
else\n\
    echo "WARP disabled (USE_WARP=false), connecting directly..."\n\
fi\n\
python -u main.py' > /app/start.sh && chmod +x /app/start.sh

ENV PYTHONUNBUFFERED=1
# Cap glibc malloc arenas so multi-threaded Python doesn'\''t balloon RSS
ENV MALLOC_ARENA_MAX=2

CMD ["/app/start.sh"]
