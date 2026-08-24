export type ReviewDecision = "approve" | "reject" | "edit";

export class ReviewJobDto {
  decision!: ReviewDecision;
  editedData?: string;
  note?: string;
  reviewedBy?: string;
}
