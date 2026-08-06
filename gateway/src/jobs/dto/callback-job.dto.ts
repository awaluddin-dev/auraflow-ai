export class CallbackJobDto {
  jobId!: string;
  status!: "completed" | "failed";
  cleanedData!: string;
  isValid!: boolean;
  attempts!: number;
  validationReason!: string;
}
