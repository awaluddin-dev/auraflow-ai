import {
  Injectable,
  Logger,
  NotFoundException,
  ConflictException,
} from "@nestjs/common";
import { InjectQueue } from "@nestjs/bullmq";
import { Queue } from "bullmq";
import { PrismaService } from "../prisma/prisma.service";
import { SubmitJobDto } from "./dto/submit-job.dto";
import { CallbackJobDto } from "./dto/callback-job.dto";
import { type Job } from "../generated/prisma";

@Injectable()
export class JobsService {
  private readonly logger = new Logger(JobsService.name);

  constructor(
    @InjectQueue(process.env.QUEUE_NAME ?? "auraflow-jobs")
    private readonly queue: Queue,
    private readonly prisma: PrismaService,
  ) {}

  async submitJob(dto: SubmitJobDto): Promise<Job> {
    const job = await this.prisma.job.create({
      data: {
        status: "queued",
        rawData: dto.rawData,
      },
    });

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

  async handleCallback(
    dto: CallbackJobDto,
  ): Promise<{ received: boolean; idempotent: boolean }> {
    // Idempotency check — cek status sekarang sebelum update
    const existing = await this.prisma.job.findUnique({
      where: { id: dto.jobId },
      select: { id: true, status: true, completedAt: true },
    });

    // Jika sudah terminal state (completed/failed), tolak dengan 409
    if (
      existing &&
      (existing.status === "completed" || existing.status === "failed")
    ) {
      this.logger.warn(
        `callback_duplicate_rejected job_id=${dto.jobId} existing_status=${existing.status}`,
      );
      throw new ConflictException(
        `Job ${dto.jobId} already in terminal state: ${existing.status}`,
      );
    }

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

    return { received: true, idempotent: false };
  }
}
