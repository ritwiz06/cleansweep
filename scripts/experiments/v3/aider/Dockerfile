# The external baseline's image: the AIDev containers' python:3.11 with Aider in its own venv, so
# the project installs into the system Python as in an AIDev container and Aider's pinned
# packages stay apart. Build: docker build -t cs-aider:0.86.2 scripts/experiments/v3/aider
FROM python:3.11
ARG AIDER_VERSION=0.86.2
RUN python -m venv /opt/aider \
    && /opt/aider/bin/pip install --no-cache-dir "aider-chat==${AIDER_VERSION}" \
    && ln -s /opt/aider/bin/aider /usr/local/bin/aider \
    && git config --system --add safe.directory '*'
