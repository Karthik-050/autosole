# syntax=docker/dockerfile:1
FROM node:{{ node_version }}-slim AS builder

WORKDIR /app

COPY package*.json yarn.lock* pnpm-lock.yaml* ./
RUN {{ install_command }}

COPY . .
{% if build_command %}
RUN {{ build_command }}
{% endif %}

FROM node:{{ node_version }}-slim AS runner

WORKDIR /app

ENV NODE_ENV=production \
    PORT={{ port }}

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app ./

RUN useradd -m -u 1000 nodeuser && chown -R nodeuser:nodeuser /app
USER nodeuser

EXPOSE {{ port }}

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:{{ port }}{{ health_check_path }} || exit 1

CMD {{ start_command_exec }}
