import {
  Injectable,
  type OnModuleInit,
  type OnModuleDestroy,
  Logger,
} from "@nestjs/common";
import { PrismaClient } from "../generated/prisma";
import { PrismaPg } from "@prisma/adapter-pg";

@Injectable()
export class PrismaService
  extends PrismaClient
  implements OnModuleInit, OnModuleDestroy
{
  private readonly logger = new Logger(PrismaService.name);

  constructor() {
    const url = process.env.RUNTIME_DATABASE_URL ?? process.env.DATABASE_URL;

    if (!url) {
      throw new Error(
        "No database URL found. Set RUNTIME_DATABASE_URL or DATABASE_URL.",
      );
    }

    const adapter = new PrismaPg({ connectionString: url });
    super({ adapter });
  }

  async onModuleInit() {
    await this.$connect();
    this.logger.log("prisma_connected");
  }

  async onModuleDestroy() {
    await this.$disconnect();
    this.logger.log("prisma_disconnected");
  }
}
