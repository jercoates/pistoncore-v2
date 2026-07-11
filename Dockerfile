# PistonCore v2 shim. Same image for both planned install paths (README.md):
# HA add-on (SUPERVISOR_TOKEN env var, supervisor auth) and plain Docker
# (data/config.json, long-lived token auth) -- shim/ha_client.py already
# branches on which is present, no build-time distinction needed.
FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only what shim/main.py actually serves/imports at runtime.
COPY shim/ shim/
COPY dashboard/ dashboard/
COPY templates/ templates/
COPY static/ static/
COPY webcore_vocab.json .
COPY picker_capability_map.json .
COPY pistoncore_attribute_translation.json .

ENV PISTONCORE_DATA_DIR=/data
VOLUME ["/data"]

EXPOSE 7777

CMD ["uvicorn", "shim.main:app", "--host", "0.0.0.0", "--port", "7777"]
