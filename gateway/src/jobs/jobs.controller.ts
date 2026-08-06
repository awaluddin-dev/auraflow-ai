import {
  Body,
  Controller,
  Get,
  HttpCode,
  Logger,
  Param,
  Post,
} from "@nestjs/common";
import { JobsService } from "./jobs.service";
import { SubmitJobDto } from "./dto/submit-job.dto";
import { CallbackJobDto } from "./dto/callback-job.dto";

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
  @HttpCode(200)
  handleCallback(@Body() dto: CallbackJobDto) {
    this.jobsService.handleCallback(dto);
    return { received: true };
  }
}
