-- CreateSchema
CREATE SCHEMA IF NOT EXISTS "auraflow";

-- CreateTable
CREATE TABLE "auraflow"."jobs" (
    "id" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'queued',
    "rawData" TEXT NOT NULL,
    "cleanedData" TEXT,
    "isValid" BOOLEAN,
    "attempts" INTEGER,
    "validationReason" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "completedAt" TIMESTAMP(3),
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "jobs_pkey" PRIMARY KEY ("id")
);
