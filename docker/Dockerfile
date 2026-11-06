# CleanSweep in a container, so the project's code runs in here and never on the host.
#   docker build -t cleansweep -f docker/Dockerfile .
#   docker run --rm -e VOYAGER_API_KEY -e VOYAGER_BASE_URL -e VOYAGER_MODEL \
#     -v "$PWD:/project:ro" -v "$PWD-cleanup:/out" cleansweep clean /project --out /out
# No secret goes into the image: the LLM settings come from the environment at run time.
FROM python:3.11

WORKDIR /opt/cleansweep
COPY requirements/core.txt requirements/core.txt
RUN pip install --no-cache-dir -r requirements/core.txt
COPY . .
# editable, so the package finds configs/ next to it; the mounted project belongs to another user
RUN pip install --no-cache-dir --no-deps -e . \
    && git config --system --add safe.directory '*'

# this container is the sandbox: clean runs the project here (there is no Docker inside it)
ENV CLEANSWEEP_SANDBOX=none
ENTRYPOINT ["cleansweep"]
CMD ["--help"]
