# Stage 1: build the Vite demonstration UI.
FROM node:20-alpine AS frontend
WORKDIR /app/src/frontend
RUN npm config set registry https://packagefeedproxy.microsoft.io/npm/
COPY src/frontend/package.json src/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY src/frontend/ ./
RUN npm run build

# Stage 2: Python runtime serving both the API and the built UI.
FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_INDEX_URL=https://packagefeedproxy.microsoft.io/pypi/simple \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

COPY src/backend/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY src/backend/app ./app
COPY data ./data
COPY scripts ./scripts
COPY --from=frontend /app/src/frontend/dist ./app/static

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
