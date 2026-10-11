FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AGENT_WORKSPACE=/app/workspace \
    AGENT_REPO_ROOT=/app/repo

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    graphviz \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY agent_utils ./agent_utils
COPY AgentExecutor.py AgentRouter.py ./

RUN pip install --upgrade pip && pip install .

RUN playwright install --with-deps chromium || true

RUN mkdir -p /app/workspace /app/repo

EXPOSE 8082

CMD ["uvicorn", "AgentExecutor:app", "--host", "0.0.0.0", "--port", "8082"]
