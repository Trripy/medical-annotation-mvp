FROM node:22-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

EXPOSE 5173

RUN npm run build

CMD ["node", "server.mjs"]
