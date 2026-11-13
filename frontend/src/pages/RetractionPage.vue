<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import AppShell from '@/components/common/AppShell.vue';
import PaperPanel from '@/components/common/PaperPanel.vue';
import EmptyState from '@/components/common/EmptyState.vue';
import ErrorNotice from '@/components/common/ErrorNotice.vue';
import StatusSeal from '@/components/common/StatusSeal.vue';
import { useAuthStore } from '@/stores/auth';
import { useRetractionStore } from '@/stores/retraction';
import type { RetractionBatch } from '@/types/retraction';
import {
  PERSONAL_FIELD_LABELS,
  RETRACTION_STATUS_LABELS,
  RETRACTION_STATUS_TONE,
} from '@/constants/retractionStatus';
import { formatDateTime } from '@/utils/formatDate';

const auth = useAuthStore();
const store = useRetractionStore();

const businessKey = ref('');
const notes = ref('');
const selected = ref<RetractionBatch | null>(null);

const batches = computed(() => store.page?.items || []);
const summary = computed(() => store.summary);
const canOperate = computed(() => auth.canRunBuild);

function fieldLabel(key: string): string {
  return PERSONAL_FIELD_LABELS[key] || key;
}

async function submit() {
  if (!businessKey.value.trim()) return;
  try {
    const batch = await store.create(businessKey.value, notes.value);
    if (!batch.already_confirmed) selected.value = batch;
  } catch {
    /* store surfaces the error */
  }
}

async function confirm(batch: RetractionBatch) {
  try {
    const result = await store.confirm(batch);
    selected.value = result;
  } catch {
    /* store surfaces the error and reloads the failed batch */
  }
}

async function restore(batch: RetractionBatch) {
  try {
    const result = await store.restore(batch);
    selected.value = result;
  } catch {
    /* store surfaces the error */
  }
}

function changeTab(next: 'all' | 'pending' | 'confirmed' | 'failed') {
  store.setStatus(next);
}

onMounted(() => {
  store.load();
});
</script>

<template>
  <AppShell>
    <header class="page__head reveal">
      <div>
        <p class="eyebrow">第六章 · Retraction</p>
        <h1 class="page__title">客户注销撤回</h1>
        <p class="page__kicker">
          客户注销后，按业务键建立撤回批次：先生成待确认的影响清单，确认后再同步隐藏当前维度、历史回溯与导出中的姓名 / 手机号 / 机构。
          匿名链号与审计计数始终保留。
        </p>
      </div>
      <div class="page__meta">
        待确认：{{ summary?.pending ?? '—' }} · 已生效：{{ summary?.confirmed ?? '—' }} · 失败：{{ summary?.failed ?? '—' }}<br />
        操作权限：{{ canOperate ? '可发起 / 确认' : '只读（服务端 403）' }}
      </div>
    </header>

    <div class="page__body">
      <ErrorNotice v-if="store.error" :message="store.error" @retry="store.load()" />
      <p v-if="store.notice" class="note-line">{{ store.notice }}</p>

      <div v-if="summary" class="grid-stats">
        <div class="stat">
          <span class="stat__label">撤回批次</span>
          <span class="stat__value">{{ summary.total }}</span>
          <span class="stat__note">每客户至多一条</span>
        </div>
        <div class="stat">
          <span class="stat__label">待确认</span>
          <span class="stat__value">{{ summary.pending }}</span>
          <span class="stat__note">仅生成清单，未隐藏</span>
        </div>
        <div class="stat">
          <span class="stat__label">已生效</span>
          <span class="stat__value">{{ summary.confirmed }}</span>
          <span class="stat__note">全链路隐藏个人字段</span>
        </div>
        <div class="stat">
          <span class="stat__label">撤回失败</span>
          <span class="stat__value" style="color: var(--danger)">{{ summary.failed }}</span>
          <span class="stat__note">已恢复上一可用版本</span>
        </div>
      </div>

      <div class="split" style="grid-template-columns: minmax(0, 1.1fr) minmax(0, 1.4fr)">
        <div class="stack">
          <PaperPanel title="发起撤回" kicker="Open a batch" hint="输入客户业务键，先生成影响清单">
            <form class="stack" @submit.prevent="submit">
              <div class="field">
                <span class="field__label">客户业务键</span>
                <input v-model="businessKey" class="input" placeholder="例如 CUST-0060" maxlength="32" :disabled="!canOperate" />
              </div>
              <div class="field">
                <span class="field__label">撤回依据 / 备注</span>
                <input v-model="notes" class="input" placeholder="例如：客户注销申请单 HX-2026-1113" maxlength="255" :disabled="!canOperate" />
              </div>
              <button class="btn btn--rust btn--small" type="submit" :disabled="!canOperate || store.creating || !businessKey.trim()">
                {{ store.creating ? '生成中…' : '生成待确认影响清单' }}
              </button>
              <p v-if="!canOperate" class="small muted">当前角色不能发起撤回（服务端同样返回 403）。</p>
            </form>
          </PaperPanel>

          <PaperPanel title="批次台账" kicker="Retraction ledger" hint="按状态筛选；确认后才隐藏个人字段">
            <template #actions>
              <div class="tabs">
                <button class="tab" :class="{ 'is-active': store.status === 'all' }" type="button" @click="changeTab('all')">全部</button>
                <button class="tab" :class="{ 'is-active': store.status === 'pending' }" type="button" @click="changeTab('pending')">待确认</button>
                <button class="tab" :class="{ 'is-active': store.status === 'confirmed' }" type="button" @click="changeTab('confirmed')">已生效</button>
                <button class="tab" :class="{ 'is-active': store.status === 'failed' }" type="button" @click="changeTab('failed')">失败</button>
              </div>
            </template>
            <div v-if="store.loading && !store.page" class="loading">读取撤回批次…</div>
            <EmptyState
              v-else-if="!batches.length"
              title="没有撤回批次"
              text="客户注销时在左侧输入业务键，先生成影响清单再确认。"
            />
            <div v-else class="stack">
              <button
                v-for="batch in batches"
                :key="batch.id"
                type="button"
                class="conflict"
                style="text-align: left; cursor: pointer; width: 100%"
                :style="{ borderLeftColor: selected?.id === batch.id ? 'var(--rust)' : 'var(--rule)' }"
                @click="selected = batch"
              >
                <div class="spread">
                  <strong class="mono">{{ batch.business_key }}</strong>
                  <StatusSeal
                    :label="RETRACTION_STATUS_LABELS[batch.status] || batch.status_label"
                    :tone="RETRACTION_STATUS_TONE[batch.status] || 'seal--neutral'"
                  />
                </div>
                <p class="small muted">
                  申请 {{ batch.requested_by || '—' }} · {{ formatDateTime(batch.requested_at) }}
                  <template v-if="batch.confirmed_at"> · 生效 {{ formatDateTime(batch.confirmed_at) }}</template>
                </p>
                <p v-if="batch.error_message" class="small" style="color: var(--danger)">{{ batch.error_message }}</p>
              </button>
            </div>
          </PaperPanel>
        </div>

        <div class="stack">
          <PaperPanel
            :title="selected ? `${selected.business_key} 影响清单` : '影响清单'"
            kicker="Impact manifest"
            :hint="selected ? '确认后才会隐藏以下个人字段' : '在左侧选择一条批次查看清单'"
          >
            <div v-if="!selected" class="loading">尚未选择批次…</div>
            <template v-else>
              <div class="spread" style="margin-bottom: 10px">
                <div class="chips">
                  <span v-for="field in selected.personal_fields" :key="field" class="chip chip--strong">
                    {{ fieldLabel(field) }}
                  </span>
                </div>
                <StatusSeal
                  :label="RETRACTION_STATUS_LABELS[selected.status] || selected.status_label"
                  :tone="RETRACTION_STATUS_TONE[selected.status] || 'seal--neutral'"
                />
              </div>

              <div class="grid-stats">
                <div class="stat">
                  <span class="stat__label">影响链版本</span>
                  <span class="stat__value">{{ selected.impact.targets.dim_versions }}</span>
                  <span class="stat__note">当前批次 {{ selected.impact.targets.dim_current_rows }} 条当前链</span>
                </div>
                <div class="stat">
                  <span class="stat__label">原始快照行</span>
                  <span class="stat__value">{{ selected.impact.targets.snapshot_rows }}</span>
                  <span class="stat__note">{{ selected.impact.targets.snapshot_sources.join(' / ') || '—' }}</span>
                </div>
                <div class="stat">
                  <span class="stat__label">冲突候选</span>
                  <span class="stat__value">{{ selected.impact.targets.conflict_items }}</span>
                  <span class="stat__note">{{ selected.impact.targets.conflict_attribute_keys.join(' / ') || '无' }}</span>
                </div>
                <div class="stat">
                  <span class="stat__label">个人字段命中</span>
                  <span class="stat__value">{{ Object.values(selected.impact.field_occurrences).reduce((a, b) => a + b, 0) }}</span>
                  <span class="stat__note">将在确认时替换为 ***</span>
                </div>
              </div>

              <table class="ledger" style="margin-top: 12px">
                <thead>
                  <tr>
                    <th>同步隐藏</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(enabled, surface) in selected.impact.will_hide" :key="surface">
                    <td class="small">{{ surface }}</td>
                    <td>
                      <StatusSeal :label="enabled ? '确认后隐藏' : '不变'" :tone="enabled ? 'seal--warn' : 'seal--neutral'" />
                    </td>
                  </tr>
                </tbody>
              </table>

              <p class="small muted" style="margin-top: 10px">
                保留：匿名业务键 <span class="mono">{{ selected.business_key }}</span>、链条数 {{ selected.impact.preserve.chain_counters }}、
                审计计数（不在撤回范围）。备份行 {{ selected.backup_rows }} 条，用于失败后恢复。
              </p>
              <p v-if="selected.error_message" class="form-error">{{ selected.error_message }}</p>

              <div class="row" style="margin-top: 12px">
                <button
                  v-if="selected.status === 'pending'"
                  class="btn btn--rust btn--small"
                  type="button"
                  :disabled="!canOperate || store.busyId === selected.id"
                  @click="confirm(selected)"
                >
                  {{ store.busyId === selected.id ? '确认中…' : '确认撤回并隐藏个人字段' }}
                </button>
                <button
                  v-if="selected.status === 'failed'"
                  class="btn btn--small"
                  type="button"
                  :disabled="!canOperate || store.busyId === selected.id"
                  @click="restore(selected)"
                >
                  恢复上一可用版本
                </button>
                <StatusSeal
                  v-if="selected.status === 'confirmed'"
                  label="已生效 · 重复执行不新增记录"
                  tone="seal--ok"
                />
              </div>
              <p class="small muted" style="margin-top: 8px">
                撤回失败时自动回滚到上一可用版本，可再次确认；已生效的批次不会重复新增记录，迟到的快照也不会恢复已撤回客户。
              </p>
            </template>
          </PaperPanel>
        </div>
      </div>
    </div>
  </AppShell>
</template>
