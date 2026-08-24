import {
  Body,
  Controller,
  Get,
  HttpCode,
  HttpStatus,
  Logger,
  Param,
  Post,
  Res,
} from "@nestjs/common";
import { type FastifyReply } from "fastify";
import { JobsService } from "./jobs.service";
import { SubmitJobDto } from "./dto/submit-job.dto";
import { CallbackJobDto } from "./dto/callback-job.dto";
import { JobsGateway } from "./job.gateway";
import type { ReviewJobDto } from "./dto/review-job.dto";

@Controller("jobs")
export class JobsController {
  constructor(
    private readonly jobsService: JobsService,
    private readonly jobsGateway: JobsGateway,
  ) {}

  @Post()
  @HttpCode(HttpStatus.ACCEPTED)
  async submit(@Body() dto: SubmitJobDto) {
    if (!dto.rawData || typeof dto.rawData !== "string") {
      return { error: "rawData is required and must be a string" };
    }
    const record = await this.jobsService.submitJob(dto);
    return {
      jobId: record.id,
      status: record.status,
      message: "Job accepted and queued for processing",
    };
  }

  // ── Static routes dulu, sebelum :id ──────────────────────────────────────

  @Post("callback")
  async handleCallback(
    @Body() dto: CallbackJobDto,
    @Res() reply: FastifyReply,
  ) {
    try {
      const result = await this.jobsService.handleCallback(dto);
      return reply.status(200).send(result);
    } catch (error: any) {
      if (error?.status === 409) {
        return reply.status(409).send({
          received: true,
          idempotent: true,
          reason: error.message,
        });
      }
      throw error;
    }
  }

  @Get("failed")
  getFailedJobs() {
    return this.jobsService.getFailedJobs();
  }

  @Get("pending-review") // ← harus di atas :id
  getPendingReviews() {
    return this.jobsService.getPendingReviews();
  }

  // ── Dynamic routes dengan :id ─────────────────────────────────────────────

  @Get(":id")
  getJob(@Param("id") id: string) {
    return this.jobsService.getJob(id);
  }

  @Get(":id/progress")
  async streamProgress(@Param("id") id: string, @Res() reply: FastifyReply) {
    await this.jobsGateway.streamProgress(id, reply);
  }

  @Post("failed/:id/retry")
  @HttpCode(HttpStatus.ACCEPTED)
  retryJob(@Param("id") id: string) {
    return this.jobsService.retryJob(id);
  }

  @Post(":id/review")
  @HttpCode(HttpStatus.OK)
  reviewJob(@Param("id") id: string, @Body() dto: ReviewJobDto) {
    return this.jobsService.reviewJob(id, dto);
  }
}
