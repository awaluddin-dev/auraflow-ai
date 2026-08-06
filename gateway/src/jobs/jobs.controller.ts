import {
  Body,
  Controller,
  Get,
  HttpCode,
  Logger,
  Param,
  Post,
  Res,
} from "@nestjs/common";
import { JobsService } from "./jobs.service";
import { SubmitJobDto } from "./dto/submit-job.dto";
import { CallbackJobDto } from "./dto/callback-job.dto";
import type { FastifyReply } from "fastify";

@Controller("jobs")
export class JobsController {
  private readonly logger = new Logger(JobsController.name);

  constructor(private readonly jobsService: JobsService) {}

  @Post()
  @HttpCode(202)
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

  @Get(":id")
  getJob(@Param("id") id: string) {
    return this.jobsService.getJob(id);
  }

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
        // Return 409 — worker interpret ini sebagai success, tidak retry
        return reply
          .status(409)
          .send({ received: true, idempotent: true, reason: error.message });
      }
      throw error;
    }
  }
}
