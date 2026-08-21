export class CallbackJobDto {
  jobId!: string;
  status!: "completed" | "failed";
  cleanedData!: string;
  isValid!: boolean;
  confidence!: number;
  attempts!: number;
  validationReason!: string;
  issues!: string[];
  sanitizeLog!: string[];
  failedReason?: string;
}
