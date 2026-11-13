import { defineStore } from 'pinia';
import { ref } from 'vue';
import type { RetractionBatch, RetractionPage, RetractionSummary } from '@/types/retraction';
import * as api from '@/api/retraction';

export const useRetractionStore = defineStore('retraction', () => {
  const page = ref<RetractionPage | null>(null);
  const summary = ref<RetractionSummary | null>(null);
  const status = ref<'all' | 'pending' | 'confirmed' | 'failed'>('all');
  const loading = ref(false);
  const error = ref('');
  const notice = ref('');
  const busyId = ref<number | null>(null);
  const creating = ref(false);

  async function load(): Promise<void> {
    loading.value = true;
    error.value = '';
    try {
      const result = await api.fetchRetractions(status.value);
      page.value = result;
      summary.value = result.summary;
    } catch (err) {
      error.value = err instanceof Error ? err.message : '加载撤回批次失败';
    } finally {
      loading.value = false;
    }
  }

  async function setStatus(next: 'all' | 'pending' | 'confirmed' | 'failed'): Promise<void> {
    status.value = next;
    await load();
  }

  async function create(businessKey: string, notes = ''): Promise<RetractionBatch> {
    creating.value = true;
    notice.value = '';
    error.value = '';
    try {
      const batch = await api.createRetraction(businessKey.trim(), notes);
      notice.value = batch.already_confirmed
        ? `${batch.business_key} 的撤回已生效，本次未新增批次`
        : `${batch.business_key} 待确认：影响清单已生成，确认后才会隐藏个人字段`;
      await load();
      return batch;
    } catch (err) {
      error.value = err instanceof Error ? err.message : '生成撤回批次失败';
      throw err;
    } finally {
      creating.value = false;
    }
  }

  async function confirm(batch: RetractionBatch): Promise<RetractionBatch> {
    busyId.value = batch.id;
    notice.value = '';
    error.value = '';
    try {
      const result = await api.confirmRetraction(batch.id);
      notice.value = result.idempotent
        ? `${batch.business_key} 撤回已生效，重复执行未新增记录`
        : `${batch.business_key} 撤回已生效：当前维度 / 回溯 / 导出中的姓名、手机号、机构已隐藏`;
      await load();
      return result;
    } catch (err) {
      error.value = err instanceof Error ? err.message : '确认撤回失败，已尝试恢复上一可用版本';
      await load();
      throw err;
    } finally {
      busyId.value = null;
    }
  }

  async function restore(batch: RetractionBatch): Promise<RetractionBatch> {
    busyId.value = batch.id;
    notice.value = '';
    error.value = '';
    try {
      const result = await api.restoreRetraction(batch.id);
      notice.value = `${batch.business_key} 已恢复上一可用版本（撤回失败，可重试）`;
      await load();
      return result;
    } catch (err) {
      error.value = err instanceof Error ? err.message : '恢复失败';
      await load();
      throw err;
    } finally {
      busyId.value = null;
    }
  }

  return { page, summary, status, loading, error, notice, busyId, creating, load, setStatus, create, confirm, restore };
});
