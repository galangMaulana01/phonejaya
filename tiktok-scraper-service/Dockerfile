# Use Node.js 20 Alpine for smaller image
FROM node:20-alpine

# Install build dependencies for canvas and chromium
RUN apk add --no-cache \
    python3 \
    make \
    g++ \
    pixman-dev \
    cairo-dev \
    pango-dev \
    libjpeg-turbo-dev \
    giflib-dev \
    chromium \
    nss \
    freetype \
    harfbuzz \
    ca-certificates \
    ttf-freefont

# Set Puppeteer/Chromium to use installed chromium
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium-browser

# Create app directory
WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci --only=production

# Copy source code
COPY src/ ./src/

# Expose port
EXPOSE 3001

# Run as non-root user for security
USER node

# Start the service
CMD ["node", "src/index.js"]