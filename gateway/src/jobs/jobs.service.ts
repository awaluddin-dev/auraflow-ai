import { Injectable, Logger, NotFoundException } from "@nestjs/common";
import { InjectQueue } from "@nestjs/bullmq";
import { Queue } from "bullmq";
import { PrismaService } from "../prisma/prisma.service";
import { SubmitJobDto } from "./dto/submit-job.dto";
import { CallbackJobDto } from "./dto/callback-job.dto";
import type { Job } from "@prisma/client";

@Injectable()
export class JobsService {
  private readonly logger = new Logger(JobsService.name);

  constructor(
    @InjectQueue(process.env.QUEUE_NAME ?? "auraflow-jobs")
    private readonly queue: Queue,
    private readonly prisma: PrismaService,
  ) {}

  async submitJob(dto: SubmitJobDto): Promise<Job> {
    // Buat record di DB dulu, dapat id
    const job = await this.prisma.job.create({
      data: {
        status: "queued",
        rawData: dto.rawData,
      },
    });

    // Push ke BullMQ dengan id dari DB sebagai jobId
    await this.queue.add(
      "process-data",
      { rawData: dto.rawData, jobId: job.id },
      { jobId: job.id },
    );

    this.logger.log(
      `job_queued job_id=${job.id} preview=${dto.rawData.slice(0, 50)}`,
    );

    return job;
  }

  async getJob(jobId: string): Promise<Job> {
    const job = await this.prisma.job.findUnique({
      where: { id: jobId },
    });

    if (!job) {
      throw new NotFoundException(`Job ${jobId} not found`);
    }

    return job;
  }

  async handleCallback(dto: CallbackJobDto): Promise<void> {
    await this.prisma.job.upsert({
      where: { id: dto.jobId },
      update: {
        status: dto.status,
        cleanedData: dto.cleanedData,
        isValid: dto.isValid,
        attempts: dto.attempts,
        validationReason: dto.validationReason,
        completedAt: new Date(),
      },
      create: {
        id: dto.jobId,
        status: dto.status,
        rawData: "",
        cleanedData: dto.cleanedData,
        isValid: dto.isValid,
        attempts: dto.attempts,
        validationReason: dto.validationReason,
        completedAt: new Date(),
      },
    });

    this.logger.log(
      `callback_received job_id=${dto.jobId} status=${dto.status} is_valid=${dto.isValid}`,
    );
  }
}
