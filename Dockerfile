# FINN backend. The cloud source probe runs at container startup when FINN_STARTUP_PROBE=1
# (in the runtime, not at build: a build-time run would test the build environment).
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY probe probe
ENV PYTHONUNBUFFERED=1
WORKDIR /app/backend
# Seed the labelled historical snapshot offline from the recorded responses (no network at build).
# Render's disk is ephemeral: every restart comes back to exactly this database; settings edits do not persist.
RUN python -m finn.ingest snapshot --replay data/snapshot
EXPOSE 8000
CMD ["sh", "-c", "uvicorn finn.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
