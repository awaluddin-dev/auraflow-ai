-- AlterTable
ALTER TABLE "auraflow"."jobs" ADD COLUMN     "failedAt" TIMESTAMP(3),
ADD COLUMN     "failedReason" TEXT;
