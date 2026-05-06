FROM node:20-alpine

WORKDIR /app

# Install deps separately for better layer caching.
COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
