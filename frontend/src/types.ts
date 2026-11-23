export type Decision = "APPROVE" | "HOLD" | "REJECT";
export type StepStatus = "running" | "pass" | "fail" | "info" | "skipped" | "error";

export interface Rule {
  rule: string;
  stage: string;
  ok: boolean | null;
  outcome?: Decision;
  message: string;
  data?: Record<string, any> | null;
}

export interface Step {
  id: number;
  seq: number;
  stage: string;
  status: StepStatus;
  summary: string | null;
  detail: any;
  duration_ms: number | null;
}

export interface Run {
  id: number;
  invoice_id: number;
  status: "queued" | "running" | "done" | "error";
  attempts: number;
  decision: Decision | null;
  deciding_rule: string | null;
  deciding_message: string | null;
  policy_version: string;
  po_id: string | null;
  po_method: string | null;
  balance_before: string | null;
  balance_after: string | null;
  linked_invoice_id: number | null;
  extraction_cached: number | null;
  trace: Rule[];
  explanation: string | null;
  explanation_source: string | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface Snapshot {
  run: Run;
  steps: Step[];
  invoice: {
    id: number; sha256: string; filename: string; pages: number; has_text_layer: number;
    invoice_number: string | null; invoice_date: string | null; subtotal: string | null; total: string | null;
    approved_run_id: number | null;
  };
  vendor: { id: string; name: string; bank_last4: string; tax_rate: string } | null;
  po: {
    id: string; description: string; status: string; total: string; open_now: string;
    lines: { sku: string; description: string; qty: string; unit_price: string; open_qty: string }[];
    allocations: { run_id: number; invoice_id: number; amount: string; qty: string; invoice_number: string }[];
  } | null;
  linked: { id: number; invoice_number: string; invoice_date: string; total: string; approved_run_id: number | null } | null;
  other_runs_of_invoice: { id: number; decision: Decision | null; deciding_rule: string | null }[];
}

export interface Sample {
  id: string; file: string; group: string; label: string; scan: boolean;
  expected_decision: Decision; expected_rule: string | null;
}

export interface HistoryRow {
  id: number; status: Run["status"]; decision: Decision | null; deciding_rule: string | null;
  deciding_message: string | null; po_id: string | null; po_method: string | null;
  balance_before: string | null; balance_after: string | null; extraction_cached: number | null;
  started_at: string; finished_at: string | null; error: string | null;
  invoice_id: number; filename: string; invoice_number: string | null; total: string | null;
  subtotal: string | null; vendor_name: string | null;
}

export interface Stats { runs: number; APPROVE: number; HOLD: number; REJECT: number; error: number; running: number; approved_amount: number }

export interface Health { status: string; policy_version: string; extract_model: string; model_credentials: boolean; stages: string[]; reset_requires_token: boolean }
