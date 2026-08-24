import { Module } from "@nestjs/common";
import { BullModule } from "@nestjs/bullmq";
import { JobsController } from "./jobs.controller";
import { JobsService } from "./jobs.service";
import { JobsGateway } from "./job.gateway";

@Module({
  imports: [
    BullModule.registerQueue({
      name: process.env.QUEUE_NAME ?? "auraflow-jobs",
    }),
  ],
  controllers: [JobsController],
  providers: [JobsService, JobsGateway],
})
export class JobsModule {}
