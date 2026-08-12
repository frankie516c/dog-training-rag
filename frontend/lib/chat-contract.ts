export type ResponseLanguage = "ko" | "en";

export interface ChatRequest {
  message: string;
  response_language: ResponseLanguage;
}

export type ChatStatus = "answered" | "insufficient_evidence";
export type EvidenceLevel = "DIRECT" | "SUPPORTING";
export type SafetyLevel = "caution" | "urgent";
export type LocatorKind = "html" | "pdf" | "pmc_article" | "dataset_definition";

export interface Locator {
  kind: LocatorKind;
  url: string;
  section: string | null;
  fragment: string | null;
  page: number | null;
  pmcid: string | null;
  doi: string | null;
  dataset_id: string | null;
  item_id: string | null;
}

export interface ChatCitation {
  card_id: string;
  source_id: string;
  source_name: string;
  canonical_url: string;
  locator: Locator;
  evidence_level: EvidenceLevel;
}

export interface SafetyNotice {
  level: SafetyLevel;
  message: string;
}

export interface ChatResponse {
  request_id: string;
  status: ChatStatus;
  answer: string;
  answer_language: ResponseLanguage;
  citations: ChatCitation[];
  limitations: string[];
  safety_notice: SafetyNotice | null;
}

export interface ChatErrorResponse {
  code: "chat_not_ready";
  message: string;
}
