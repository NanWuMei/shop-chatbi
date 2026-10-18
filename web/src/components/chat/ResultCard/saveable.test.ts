import { describe, expect, it } from 'vitest';
import { saveDisabledReason } from './saveable';

/** SDD §3.5 五态置灰表（表驱动，AC-15/F35） */
describe('saveDisabledReason 置灰判定纯函数', () => {
  const cases: Array<{ name: string; input: Parameters<typeof saveDisabledReason>[0]; disabled: boolean; tooltip: string }> = [
    {
      name: '澄清进行中 → 请先完成口径确认',
      input: { terminal: 'clarification', saveable: true, chartFailed: false, clarifyStatus: 'pending' },
      disabled: true,
      tooltip: '请先完成口径确认',
    },
    {
      name: '已取消澄清 → 请先完成口径确认',
      input: { terminal: 'answer', saveable: true, chartFailed: false, clarifyStatus: 'cancelled' },
      disabled: true,
      tooltip: '请先完成口径确认',
    },
    {
      name: 'rejection（业务拒答）→ 该结果无法保存',
      input: { terminal: 'rejection', saveable: false, chartFailed: false },
      disabled: true,
      tooltip: '该结果无法保存',
    },
    {
      name: 'answer 空结果 → 暂无数据，无法保存',
      input: { terminal: 'answer', saveable: false, chartFailed: false },
      disabled: true,
      tooltip: '暂无数据，无法保存',
    },
    {
      name: '已取消 → 取数未成功，无法保存',
      input: { terminal: 'cancelled', saveable: false, chartFailed: false },
      disabled: true,
      tooltip: '取数未成功，无法保存',
    },
    {
      name: 'error 终态 → 取数未成功，无法保存',
      input: { terminal: 'error', saveable: false, chartFailed: false },
      disabled: true,
      tooltip: '取数未成功，无法保存',
    },
    {
      name: '图表渲染失败 → 图表加载失败，暂不能保存',
      input: { terminal: 'answer', saveable: true, chartFailed: true },
      disabled: true,
      tooltip: '图表加载失败，暂不能保存',
    },
    {
      name: 'answer 非空且图正常 → 可保存',
      input: { terminal: 'answer', saveable: true, chartFailed: false },
      disabled: false,
      tooltip: '',
    },
  ];

  for (const c of cases) {
    it(c.name, () => {
      const result = saveDisabledReason(c.input);
      expect(result.disabled).toBe(c.disabled);
      expect(result.tooltip).toBe(c.tooltip);
    });
  }
});
