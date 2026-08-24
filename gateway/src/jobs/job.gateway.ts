import { Injectable, Logger, type OnModuleDestroy } from "@nestjs/common";
import type { FastifyReply } from "fastify";
import Redis from "ioredis";

@Injectable()
export class JobsGateway implements OnModuleDestroy {
  private readonly logger = new Logger(JobsGateway.name);
  private readonly subscribers = new Map<string, Redis>();

  // Satu Redis connection per SSE client — karena subscribe() blokir connection
  private createSubscriber(): Redis {
    return new Redis(process.env.REDIS_URL ?? "redis://localhost:6379", {
      maxRetriesPerRequest: null,
      lazyConnect: true,
    });
  }

  async streamProgress(jobId: string, reply: FastifyReply): Promise<void> {
    const subscriber = this.createSubscriber();
    const channel = `job-progress:${jobId}`;

    // SSE headers
    reply.raw.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no", // disable nginx buffering
    });

    const send = (event: string, data: object) => {
      reply.raw.write(`event: ${event}\n`);
      reply.raw.write(`data: ${JSON.stringify(data)}\n\n`);
    };

    // Kirim event awal
    send("connected", { jobId, channel });
    this.logger.log(`sse_connected job_id=${jobId}`);

    await subscriber.connect();
    await subscriber.subscribe(channel);

    this.subscribers.set(jobId, subscriber);

    subscriber.on("message", (_channel: string, message: string) => {
      try {
        const data = JSON.parse(message);
        send("progress", data);
        this.logger.debug(`sse_event job_id=${jobId} stage=${data.stage}`);

        // Tutup koneksi jika job terminal
        if (
          data.stage === "completed" || 
          data.stage === "failed" || 
          data.stage === "pending_review"
        ) {
          send("done", { jobId, stage: data.stage });
          this.logger.log(`sse_closed job_id=${jobId} stage=${data.stage}`);
          subscriber.disconnect();
          this.subscribers.delete(jobId);
          reply.raw.end();
        }
      } catch (e) {
        this.logger.error(`sse_parse_error job_id=${jobId} error=${e}`);
      }
    });

    subscriber.on("error", (err: Error) => {
      this.logger.error(`sse_redis_error job_id=${jobId} error=${err.message}`);
      reply.raw.end();
    });

    // Cleanup jika client disconnect
    reply.raw.on("close", () => {
      this.logger.log(`sse_client_disconnected job_id=${jobId}`);
      subscriber.disconnect();
      this.subscribers.delete(jobId);
    });

    // Keepalive setiap 15 detik supaya koneksi tidak timeout
    const keepalive = setInterval(() => {
      if (reply.raw.destroyed) {
        clearInterval(keepalive);
        return;
      }
      reply.raw.write(": keepalive\n\n");
    }, 15_000);

    reply.raw.on("close", () => clearInterval(keepalive));
  }

  async onModuleDestroy() {
    for (const [jobId, sub] of this.subscribers) {
      this.logger.log(`sse_cleanup job_id=${jobId}`);
      sub.disconnect();
    }
    this.subscribers.clear();
  }
}
