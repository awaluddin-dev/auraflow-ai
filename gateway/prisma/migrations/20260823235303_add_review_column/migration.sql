-- AlterTable
ALTER TABLE "auraflow"."jobs" ADD COLUMN     "reviewedAt" TIMESTAMP(3),
ADD COLUMN     "reviewedBy" TEXT;
