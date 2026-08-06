import { Module } from "@nestjs/common";
import { QueueModule } from "./queue/queue.module";
import { JobsModule } from "./jobs/jobs.module";
import { PrismaModule } from "./prisma/prisma.module";

@Module({
  imports: [PrismaModule, QueueModule, JobsModule],
})
export class AppModule {}
