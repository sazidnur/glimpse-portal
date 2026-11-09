FROM node:22-bookworm-slim

# Chrome Headless Shell's libraries, and Noto fonts (Bengali included) as a fallback for the template's own fonts.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libdbus-1-3 libatk1.0-0 libgbm-dev libasound2 libxrandr2 libxkbcommon-dev libxfixes3 \
    libxcomposite1 libxdamage1 libatk-bridge2.0-0 libpango-1.0-0 libcairo2 libcups2 fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY template/package*.json ./
RUN npm ci || npm install
COPY template/ ./
RUN version=$(node -p "require('remotion/package.json').version") \
    && npm install --no-save "@remotion/bundler@$version" "@remotion/renderer@$version" \
    && node -e "import('@remotion/renderer').then((r) => r.ensureBrowser())"
COPY worker.mjs ./

USER node
CMD ["node", "worker.mjs"]
