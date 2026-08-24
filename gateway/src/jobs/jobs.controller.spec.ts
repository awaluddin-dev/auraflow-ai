import { test, expect, describe, mock, beforeEach } from "bun:test";
import { JobsController } from "./jobs.controller";

describe("JobsController", () => {
  let jobsController: JobsController;
  let mockJobsService: any;
  let mockJobsGateway: any;

  beforeEach(() => {
    mockJobsService = {
      submitJob: mock(() => Promise.resolve({ id: "job-123", status: "queued" })),
      handleCallback: mock(() => Promise.resolve({ received: true })),
      getPendingReviews: mock(() => Promise.resolve([])),
      getJob: mock((id: string) => Promise.resolve({ id, status: "queued" })),
      retryJob: mock((id: string) => Promise.resolve({ id, status: "retrying" })),
      reviewJob: mock((id: string, dto: any) => Promise.resolve({ id, status: "processing" })),
    };

    mockJobsGateway = {
      streamProgress: mock(() => Promise.resolve()),
    };

    jobsController = new JobsController(mockJobsService, mockJobsGateway);
  });

  test("submit() should call submitJob on service", async () => {
    const dto = { rawData: "test data" };
    const result = await jobsController.submit(dto);
    
    expect(result.jobId).toBe("job-123");
    expect(result.status).toBe("queued");
    expect(mockJobsService.submitJob).toHaveBeenCalledWith(dto);
  });

  test("submit() should return error if rawData is empty", async () => {
    const dto = { rawData: "" };
    const result = await jobsController.submit(dto);
    
    expect((result as any).error).toBeDefined();
    expect(mockJobsService.submitJob).not.toHaveBeenCalled();
  });

  test("handleCallback() should return success", async () => {
    const dto = { jobId: "job-123", is_valid: true, confidence: 0.9, attempt: 1 };
    const mockReply = { status: mock(() => mockReply), send: mock((val) => val) };
    
    const result = await jobsController.handleCallback(dto, mockReply as any);
    
    expect(result).toEqual({ received: true });
    expect(mockJobsService.handleCallback).toHaveBeenCalledWith(dto);
  });

  test("getJob() should return job from service", async () => {
    const result = await jobsController.getJob("job-123");
    
    expect(result.id).toBe("job-123");
    expect(mockJobsService.getJob).toHaveBeenCalledWith("job-123");
  });
  
  test("reviewJob() should call reviewJob on service", async () => {
    const dto = { decision: "approve" as any };
    const result = await jobsController.reviewJob("job-123", dto);
    
    expect(result.status).toBe("processing");
    expect(mockJobsService.reviewJob).toHaveBeenCalledWith("job-123", dto);
  });
});
