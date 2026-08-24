export class CallbackJobDto {
  jobId!: string;
  status!: "completed" | "failed" | "pending_review";
  cleanedData!: string;
  isValid!: boolean;
  confidence!: number;
  attempts!: number;
  validationReason!: string;
  issues!: string[];
  sanitizeLog!: string[];
  hitlReasons?: string[];
  failedReason?: string;
}
