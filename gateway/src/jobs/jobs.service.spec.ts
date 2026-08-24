import { test, expect, describe, mock, beforeEach } from "bun:test";
import { JobsService } from "./jobs.service";

describe("JobsService", () => {
  let jobsService: JobsService;
  let mockQueue: any;
  let mockPrisma: any;

  beforeEach(() => {
    mockQueue = {
      add: mock(() => Promise.resolve({ id: "job-123" })),
    };

    mockPrisma = {
      job: {
        create: mock((args) => Promise.resolve({ id: "db-job-123", ...args.data })),
        findUnique: mock(() => Promise.resolve({ id: "db-job-123", status: "queued" })),
        findMany: mock(() => Promise.resolve([])),
        upsert: mock((args) => Promise.resolve({ id: "db-job-123", ...args.create })),
        update: mock((args) => Promise.resolve({ id: "db-job-123", ...args.data })),
      },
    };

    jobsService = new JobsService(mockQueue, mockPrisma);
  });

  test("should submit job to queue and database", async () => {
    const dto = { rawData: "test data", priority: "high" as any };
    const result = await jobsService.submitJob(dto);

    expect(result.id).toBe("db-job-123");
    expect(result.status).toBe("queued");
    expect(mockPrisma.job.create).toHaveBeenCalled();
    expect(mockQueue.add).toHaveBeenCalled();
  });

  test("should handle callback and return success status", async () => {
    mockPrisma.job.findUnique.mockResolvedValue({ id: "db-job-123", status: "processing" });
    mockPrisma.job.update = mock((args) => Promise.resolve({ ...args.data }));

    const dto = { jobId: "db-job-123", is_valid: true, confidence: 0.95, attempt: 1 };
    const result = await jobsService.handleCallback(dto as any);

    expect(result.received).toBe(true);
    expect(mockPrisma.job.upsert).toHaveBeenCalled();
  });

  test("should return 409 conflict if callback is idempotent (already completed)", async () => {
    mockPrisma.job.findUnique.mockResolvedValue({ id: "db-job-123", status: "completed" });
    
    const dto = { jobId: "db-job-123", is_valid: true, confidence: 0.95, attempt: 1 };
    
    try {
      await jobsService.handleCallback(dto);
      expect(true).toBe(false); // Should not reach here
    } catch (e: any) {
      expect(e.status).toBe(409);
    }
  });

  test("should return pending reviews", async () => {
    mockPrisma.job.findMany.mockResolvedValue([{ id: "db-job-123", status: "pending_review" }]);
    const results = await jobsService.getPendingReviews();
    expect(results.length).toBe(1);
    expect(results[0].status).toBe("pending_review");
  });
});
