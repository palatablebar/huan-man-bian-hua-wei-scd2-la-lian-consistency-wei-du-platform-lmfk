import { request } from '@/utils/request';
import type { RetractionBatch, RetractionPage } from '@/types/retraction';

export function fetchRetractions(status = 'all') {
  return request<RetractionPage>(`/retractions?status=${encodeURIComponent(status)}`);
}

export function previewRetraction(businessKey: string) {
  return request<{ business_key: string; impact: RetractionBatch['impact']; existing: RetractionBatch | null }>(
    `/retractions/preview?business_key=${encodeURIComponent(businessKey)}`,
  );
}

export function createRetraction(businessKey: string, notes = '') {
  return request<RetractionBatch>('/retractions', {
    method: 'POST',
    body: { business_key: businessKey, notes },
  });
}

export function confirmRetraction(batchId: number) {
  return request<RetractionBatch>(`/retractions/${batchId}/confirm`, { method: 'POST' });
}

export function restoreRetraction(batchId: number) {
  return request<RetractionBatch>(`/retractions/${batchId}/restore`, { method: 'POST' });
}
