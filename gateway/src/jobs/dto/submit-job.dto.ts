export type JobPriority = "urgent" | "high" | "normal" | "low";

export const PRIORITY_MAP: Record<JobPriority, number> = {
  urgent: 1,
  high: 2,
  normal: 3,
  low: 4,
};

export class SubmitJobDto {
  rawData!: string;
  priority?: JobPriority;
}
