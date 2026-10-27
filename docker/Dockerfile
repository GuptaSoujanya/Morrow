# One image for every bot's container: Chromium on a virtual screen you can watch
# in a web page (noVNC), the claude CLI and the Playwright MCP the browser agent drives it with. The repo is mounted at /app
# (docker-compose.yml), so the code, .env, user/ and database/ are the
# ones on your machine. Build: docker compose build
FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium chromium-driver xvfb x11vnc xauth novnc websockify \
        fonts-liberation fonts-noto-color-emoji ca-certificates git curl procps poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install -g @anthropic-ai/claude-code && npm cache clean --force

COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock

RUN useradd --create-home --uid 1000 bot
USER bot
# Fetch the Playwright MCP once, so no run waits for npx (keep in step with BROWSER_AGENT_MCP).
RUN npx -y @playwright/mcp@0.0.83 --help >/dev/null

ENV CHROME_BINARY=/usr/bin/chromium \
    CHROMEDRIVER=/usr/bin/chromedriver \
    DISPLAY=:99 \
    SCREEN_SIZE=1600x1000 \
    CHROME_WINDOW_SIZE=1600,1000 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/entrypoint
ENTRYPOINT ["entrypoint"]
EXPOSE 6080
CMD ["python3", "-m", "pipeline", "run"]
