FROM node:22-alpine

WORKDIR /worker

COPY package.json ./
RUN npm install

COPY . .

ENTRYPOINT ["npx", "wrangler"]
CMD ["deploy"]
