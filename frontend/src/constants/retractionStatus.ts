export const RETRACTION_STATUS_LABELS: Record<string, string> = {
  pending: '待确认',
  confirmed: '已生效',
  failed: '撤回失败',
};

export const RETRACTION_STATUS_TONE: Record<string, string> = {
  pending: 'seal--warn',
  confirmed: 'seal--ok',
  failed: 'seal--bad',
};

export const PERSONAL_FIELD_LABELS: Record<string, string> = {
  full_name: '客户姓名',
  mobile: '手机号',
  org_code: '归属机构',
};
