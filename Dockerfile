# Stage 1: Frontend build
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Backend
FROM python:3.12-slim
WORKDIR /app

# Install gh CLI
RUN apt-get update && \
    apt-get install -y curl git && \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null && \
    apt-get update && \
    apt-get install -y gh && \
    rm -rf /var/lib/apt/lists/*

# Install Copilot extension
RUN gh extension install github/gh-copilot

# Install uv and Python deps
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy app code
COPY relay/ ./relay/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Copy frontend build
COPY --from=frontend /app/frontend/dist ./frontend/dist

EXPOSE 8080
ENTRYPOINT ["uv", "run", "relay"]
CMD ["dev"]
