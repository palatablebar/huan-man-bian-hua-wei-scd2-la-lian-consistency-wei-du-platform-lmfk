import type { Paged } from './api';

export type RetractionStatus = 'pending' | 'confirmed' | 'failed';

export interface RetractionImpact {
  business_key: string;
  personal_fields: string[];
  targets: {
    dim_versions: number;
    dim_current_rows: number;
    snapshot_rows: number;
    snapshot_sources: string[];
    conflict_items: number;
    conflict_attribute_keys: string[];
  };
  will_hide: Record<string, boolean>;
  preserve: Record<string, string | number>;
  field_occurrences: Record<string, number>;
  pre_retraction_run_id: number | null;
  applied?: Record<string, number>;
  restored?: Record<string, number>;
  will_retract: boolean;
}

export interface RetractionBatch {
  id: number;
  business_key: string;
  status: RetractionStatus;
  status_label: string;
  impact: RetractionImpact;
  requested_by: string;
  requested_at: string | null;
  confirmed_by: string;
  confirmed_at: string | null;
  attempt_count: number;
  baseline_run_id: number | null;
  applied_run_id: number | null;
  restored_at: string | null;
  error_message: string;
  notes: string;
  personal_fields: string[];
  anonymous_key_preserved: boolean;
  backup_rows: number;
  idempotent?: boolean;
  already_confirmed?: boolean;
}

export interface RetractionSummary {
  total: number;
  pending: number;
  confirmed: number;
  failed: number;
  by_status: Record<string, number>;
  labels: Record<string, string>;
  personal_fields: string[];
}

export interface RetractionPage extends Paged<RetractionBatch> {
  summary: RetractionSummary;
}
