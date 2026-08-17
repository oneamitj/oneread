# syntax=docker/dockerfile:1

# --- stage 1: the browser bundle -------------------------------------------
FROM node:22-alpine AS web
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
# `npm ci` and nothing else. The fallback that used to sit here (`|| npm
# install`) meant any lockfile drift silently resolved fresh versions instead,
# so the lockfile stopped being a control exactly when it mattered. A build that
# can't honour the lockfile should stop.
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- stage 2: python deps and the model ------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    SUPERTONIC_CACHE_DIR=/opt/supertonic \
    ONEREAD_DATA_DIR=/data \
    ONEREAD_STATIC_DIR=/app/frontend/dist

RUN apt-get update \
 && apt-get install -y --no-install-recommends libsndfile1 curl \
 && rm -rf /var/lib/apt/lists/*

# Every upload format is read in pure Python except .doc and .ppt, which have
# no reader worth trusting. Uncomment to accept those two as well. It costs
# roughly 400 MB of image, which is why it isn't the default; without it those
# files are turned away with a note to save them as .docx or .pptx.
# RUN apt-get update \
#  && apt-get install -y --no-install-recommends \
#       libreoffice-core libreoffice-writer libreoffice-impress \
#  && rm -rf /var/lib/apt/lists/*
# ENV ONEREAD_SOFFICE_PATH=/usr/bin/soffice

WORKDIR /app

# Dependencies come from the lockfile, with hashes, and --require-hashes makes
# pip refuse any package whose bytes don't match. Without it the versions here
# were whatever PyPI happened to be serving at build time — across twenty
# packages, several of which parse documents uploaded by strangers.
#
# Copied and installed before the source, so editing the app doesn't invalidate
# this layer. Regenerate after changing pyproject.toml:
#   cd backend && uv pip compile pyproject.toml --generate-hashes --universal \
#     --python-version 3.12 -o requirements.txt
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /app/backend/requirements.txt

# --no-deps because the lockfile above is the whole dependency set already, and
# the local directory has no hash of its own to check.
COPY backend/ /app/backend/
RUN pip install --no-cache-dir --no-deps /app/backend

# Pull the ~385 MB model at build time so a running container never reaches
# out to the network. This is the whole point of "no external dependency".
RUN python -c "from supertonic import TTS; TTS(auto_download=True)" \
 && chmod -R a+rX /opt/supertonic

COPY --from=web /build/dist /app/frontend/dist

RUN useradd --system --uid 10001 --create-home oneread \
 && mkdir -p /data \
 && chown -R oneread:oneread /data /app
USER oneread

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

# One worker on purpose: the model is held in memory once, and synthesis runs
# on a single background thread behind it.
#
# --no-proxy-headers is deliberate, and it has to be said out loud: uvicorn
# enables proxy headers by default and trusts loopback, which means it replaces
# the connecting address with whatever X-Forwarded-For claims. Rate limits keyed
# on that address then reset on every request. Nothing here needs the forwarded
# scheme (cookie_secure is set explicitly), so the whole mechanism comes off.
# Behind a reverse proxy, turn it back on naming the proxy's own address:
#   --proxy-headers --forwarded-allow-ips 172.18.0.2
# Never "*", and never the default, unless nothing but the proxy can reach the
# port.
CMD ["uvicorn", "oneread.main:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers"]
