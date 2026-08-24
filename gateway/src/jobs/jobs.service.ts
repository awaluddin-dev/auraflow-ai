import {
  Injectable,
  Logger,
  NotFoundException,
  ConflictException,
} from "@nestjs/common";
import { InjectQueue } from "@nestjs/bullmq";
import { Queue } from "bullmq";
import { PrismaService } from "../prisma/prisma.service";
import {
  PRIORITY_MAP,
  SubmitJobDto,
  type JobPriority,
} from "./dto/submit-job.dto";
import { CallbackJobDto } from "./dto/callback-job.dto";
import { type Job } from "@prisma/client";
import type { ReviewJobDto } from "./dto/review-job.dto";

@Injectable()
export class JobsService {
  private readonly logger = new Logger(JobsService.name);

  constructor(
    @InjectQueue(process.env.QUEUE_NAME ?? "auraflow-jobs")
    private readonly queue: Queue,
    private readonly prisma: PrismaService,
  ) {}

  async submitJob(dto: SubmitJobDto): Promise<Job> {
    const priority = dto.priority ?? "normal";
    const bullPriority = PRIORITY_MAP[priority];
    const job = await this.prisma.job.create({
      data: { status: "queued", rawData: dto.rawData, priority },
    });

    await this.queue.add(
      "process-data",
      { rawData: dto.rawData, jobId: job.id },
      {
        jobId: job.id,
        priority: bullPriority,
        attempts: 3,
        backoff: { type: "exponential", delay: 2000 },
        removeOnComplete: 100,
        removeOnFail: false,
      },
    );

    this.logger.log(
      `job_queued job_id=${job.id} priority=${priority}(${bullPriority}) preview=${dto.rawData.slice(0, 50)}`,
    );

    return job;
  }

  async getJob(jobId: string): Promise<Job> {
    const job = await this.prisma.job.findUnique({ where: { id: jobId } });
    if (!job) throw new NotFoundException(`Job ${jobId} not found`);
    return job;
  }

  async getFailedJobs(): Promise<Job[]> {
    return this.prisma.job.findMany({
      where: { status: "failed" },
      orderBy: { failedAt: "desc" },
      take: 50,
    });
  }

  async retryJob(jobId: string): Promise<Job> {
    const existing = await this.prisma.job.findUnique({ where: { id: jobId } });

    if (!existing) throw new NotFoundException(`Job ${jobId} not found`);
    if (existing.status !== "failed") {
      throw new ConflictException(
        `Job ${jobId} is not in failed state (current: ${existing.status})`,
      );
    }

    const updated = await this.prisma.job.update({
      where: { id: jobId },
      data: {
        status: "queued",
        failedReason: null,
        failedAt: null,
        cleanedData: null,
        isValid: null,
        attempts: null,
        validationReason: null,
        completedAt: null,
      },
    });

    const priority = (existing.priority as JobPriority) ?? "normal";
    const bullPriority = PRIORITY_MAP[priority];

    await this.queue.add(
      "process-data",
      { rawData: existing.rawData, jobId: existing.id },
      {
        jobId: `retry-${existing.id}-${Date.now()}`,
        priority: bullPriority, // pertahankan priority asli saat retry
        attempts: 3,
        backoff: { type: "exponential", delay: 2000 },
        removeOnFail: false,
      },
    );

    this.logger.log(`job_retry job_id=${jobId} priority=${priority}`);
    return updated;
  }

  async handleCallback(
    dto: CallbackJobDto,
  ): Promise<{ received: boolean; idempotent: boolean }> {
    const existing = await this.prisma.job.findUnique({
      where: { id: dto.jobId },
      select: { id: true, status: true },
    });

    // Hanya tolak duplicate jika sudah terminal (completed/failed)
    // pending_review bisa di-update
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
        confidence: dto.confidence,
        attempts: dto.attempts,
        validationReason: dto.validationReason,
        issues: dto.issues ?? [],
        sanitizeLog: dto.sanitizeLog ?? [],
        failedReason: dto.failedReason ?? null,
        failedAt: dto.status === "failed" ? new Date() : null,
        completedAt: dto.status === "completed" ? new Date() : null,
      },
      create: {
        id: dto.jobId,
        status: dto.status,
        rawData: "",
        cleanedData: dto.cleanedData,
        isValid: dto.isValid,
        confidence: dto.confidence,
        attempts: dto.attempts,
        validationReason: dto.validationReason,
        issues: dto.issues ?? [],
        sanitizeLog: dto.sanitizeLog ?? [],
        failedReason: dto.failedReason ?? null,
        failedAt: dto.status === "failed" ? new Date() : null,
        completedAt: dto.status === "completed" ? new Date() : null,
      },
    });

    this.logger.log(
      `callback_received job_id=${dto.jobId} status=${dto.status} is_valid=${dto.isValid}`,
    );

    return { received: true, idempotent: false };
  }
  async getPendingReviews(): Promise<Job[]> {
    return this.prisma.job.findMany({
      where: { status: "pending_review" },
      orderBy: { createdAt: "asc" },
    });
  }

  async reviewJob(jobId: string, dto: ReviewJobDto): Promise<Job> {
    const existing = await this.prisma.job.findUnique({
      where: { id: jobId },
    });

    if (!existing) throw new NotFoundException(`Job ${jobId} not found`);

    if (existing.status !== "pending_review") {
      throw new ConflictException(
        `Job ${jobId} is not pending review (current: ${existing.status})`,
      );
    }

    if (dto.decision === "edit" && !dto.editedData) {
      throw new ConflictException(
        "editedData is required when decision is edit",
      );
    }

    // Update DB
    const updated = await this.prisma.job.update({
      where: { id: jobId },
      data: {
        status: dto.decision === "approve" ? "completed" : "queued",
        reviewedAt: new Date(),
        reviewedBy: dto.reviewedBy ?? "anonymous",
        completedAt: dto.decision === "approve" ? new Date() : null,
      },
    });

    // Publish resume signal ke worker via Redis
    // Worker subscribe ke channel ini dan resume graph
    const resumePayload = JSON.stringify({
      jobId,
      decision: dto.decision,
      editedData: dto.editedData ?? "",
      note: dto.note ?? "",
    });

    // Pakai Redis pub/sub yang sama dengan SSE progress
    // Worker punya subscriber khusus untuk resume
    await this.publishResume(jobId, resumePayload);

    this.logger.log(
      `job_review job_id=${jobId} decision=${dto.decision} by=${dto.reviewedBy}`,
    );

    return updated;
  }

  private async publishResume(jobId: string, payload: string): Promise<void> {
    const { Redis } = await import("ioredis");
    const redis = new Redis(process.env.REDIS_URL ?? "redis://localhost:6379");
    try {
      await redis.publish(`job-resume:${jobId}`, payload);
      this.logger.log(`resume_published job_id=${jobId}`);
    } finally {
      await redis.quit();
    }
  }
}
