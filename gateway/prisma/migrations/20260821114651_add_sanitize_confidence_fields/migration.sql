-- AlterTable
ALTER TABLE "auraflow"."jobs" ADD COLUMN     "confidence" DOUBLE PRECISION,
ADD COLUMN     "issues" TEXT[] DEFAULT ARRAY[]::TEXT[],
ADD COLUMN     "sanitizeLog" TEXT[] DEFAULT ARRAY[]::TEXT[],
ADD COLUMN     "sanitizedData" TEXT;
