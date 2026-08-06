import { Module } from "@nestjs/common";
import { BullModule } from "@nestjs/bullmq";
import { resolve } from "node:path";
import { config } from "dotenv";

config({ path: resolve(__dirname, "../../.env") });

@Module({
  imports: [
    BullModule.forRootAsync({
      useFactory: () => ({
        connection: {
          url: process.env.REDIS_URL ?? "redis://localhost:6379",
        },
      }),
    }),
  ],
  exports: [BullModule],
})
export class QueueModule {}
