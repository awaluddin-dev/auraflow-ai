import "reflect-metadata";
import { NestFactory } from "@nestjs/core";
import {
  FastifyAdapter,
  type NestFastifyApplication,
} from "@nestjs/platform-fastify";
import { Logger } from "@nestjs/common";
import { AppModule } from "./app.module";
import { config } from "dotenv";
import { resolve } from "node:path";

config({ path: resolve(__dirname, "../../.env") });

async function bootstrap() {
  const logger = new Logger("Bootstrap");
  const port = Number(process.env.PORT ?? 3000);

  const app = await NestFactory.create<NestFastifyApplication>(
    AppModule,
    new FastifyAdapter({
      logger: false, // NestJS handles logging
    }),
  );

  // Fastify perlu listen ke 0.0.0.0 untuk Docker/container
  await app.listen(port, "0.0.0.0");
  logger.log(`gateway_started port=${port} runtime=bun adapter=fastify`);
}

bootstrap();
