# StateChecker, Python 3 and gunicorn, for the Synaptic appliance.
#
#   docker build -f docker/Dockerfile -t synaptic/statechecker:<version> .
#
# The UI is built HERE, not when the container starts as upstream's start.sh
# did: that ran npm install against the internet on first boot, which an
# airgapped appliance cannot do. MongoDB is its own container (see the
# product's compose), not a service started inside this one.
#
# Upstream's build/Dockerfile (Ubuntu 16.04, Python 2, Apache, MongoDB 3.6 in
# one container) is kept for the APIC app build and is not used here.

# ── the UI ──────────────────────────────────────────────────────────────────
# Angular 6 from 2018: Node 10 is the newest it builds with. Only the build
# runs on it; nothing from this stage ships except the static files.
FROM node:10.24.1 AS ui
WORKDIR /ui
COPY UIAssets/package.json UIAssets/package-lock.json ./
RUN npm ci --no-audit --no-fund --loglevel=error
COPY UIAssets/ ./
# --base-href ./ with hash routing and a relative API base: the app works
# under any prefix (/statechecker/, /<node>/statechecker/) without a rebuild.
RUN ./node_modules/.bin/ng build -c standalone --base-href ./

# ── the service ─────────────────────────────────────────────────────────────
FROM python:3.13.15-slim

# procps: fabric process listing (ps). openssh-client: switch access over SSH
# through the APIC, which the fabric credential check and snapshots can use.
RUN apt-get update \
 && apt-get install -y --no-install-recommends procps openssh-client \
 && rm -rf /var/lib/apt/lists/*

ENV APP_DIR=/home/app \
    DATA_DIR=/home/app/data/snapshots \
    TMP_DIR=/home/app/data/tmp \
    LOG_DIR=/home/app/log \
    UI_DIR=/home/app/src/UIAssets \
    STARTED_FILE=/home/app/run/started \
    STATUS_FILE=/home/app/run/status \
    DEBUG=0 \
    LOG_LEVEL=20 \
    LOG_ROTATE=1 \
    PYTHONUNBUFFERED=1

COPY build/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore -r /tmp/requirements.txt

WORKDIR /home/app/src/Service
COPY Service/ /home/app/src/Service/
# config.py reads the app's name and version from app.json beside it
COPY app.json /home/app/src/Service/app.json
COPY --from=ui /ui/dist/ /home/app/src/UIAssets/
COPY docker/entrypoint.sh /usr/local/bin/statechecker-entrypoint

# config.py reads version.txt: commit, date, epoch, author, branch
ARG SOURCE_COMMIT=unknown
ARG SOURCE_DATE=unknown
RUN printf '%s\n%s\n0\nsynaptic\nsynaptic\n' "$SOURCE_COMMIT" "$SOURCE_DATE" > version.txt \
 && rm -rf tests \
 && useradd --uid 1000 --home-dir /home/app --no-create-home app \
 && mkdir -p /home/app/data/snapshots /home/app/data/tmp /home/app/log /home/app/run \
 && chown -R app:app /home/app/data /home/app/log /home/app/run \
 && chmod 0755 /usr/local/bin/statechecker-entrypoint

USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/aci/app-status/', timeout=4).status==200 else 1)"
ENTRYPOINT ["/usr/local/bin/statechecker-entrypoint"]
