FROM node:22-bookworm-slim AS matter_runtime
WORKDIR /matter
COPY 08_servises/matter_bridge/package*.json ./
RUN npm ci --omit=dev --ignore-scripts

FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/HomeControl

WORKDIR /opt/HomeControl

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=matter_runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=matter_runtime /matter/node_modules /opt/HomeControl/08_servises/matter_bridge/node_modules

USER 10001:10001
EXPOSE 8080

CMD ["python", "-m", "uvicorn", "02_HCM.main:app", "--host", "0.0.0.0", "--port", "8080"]
