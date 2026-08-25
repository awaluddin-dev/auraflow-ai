FROM oven/bun:1.2-alpine

WORKDIR /app

# Copy dependency files
COPY package.json bun.lock ./

# Install dependencies
RUN bun install --frozen-lockfile --ignore-scripts

# Copy source
COPY src/ ./src/
COPY prisma/ ./prisma/
COPY tsconfig.json ./

# Generate Prisma client
RUN bunx prisma@7.9.1 generate

EXPOSE 3000

CMD ["bun", "run", "src/main.ts"]