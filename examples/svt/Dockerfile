# Multi-stage build for svt
FROM python:3.12-slim
WORKDIR /app

# Runtime dependencies (from spec.runtime.dependencies)
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates gnupg && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && apt-get install -y --no-install-recommends nodejs && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv
RUN npm install -g pnpm turbo

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["adk", "web", ".", "--port", "8000", "--host", "0.0.0.0"]
