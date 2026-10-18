/**
 * 「存为报表」置灰判定（纯函数，NFR-2）：SDD §3.5 五态表的前端第一关。
 * 与后端 E_REPORT_NOT_SAVEABLE 第二关对应；文案固定，不另写业务话术。
 */
import type { TerminalEvent } from '../../../api/types';

export interface SaveGuardInput {
  /** 当前上下文终态；问数流中的卡片才有（报表查看页无保存） */
  terminal: TerminalEvent | null;
  /** 后端派生 saveable（= answer 且 rows 非空）；历史还原的 answer 切片也带 */
  saveable: boolean;
  /** 图表处于渲染失败降级态 */
  chartFailed: boolean;
  /** 澄清卡最终态（terminal=clarification 时看 payload.status） */
  clarifyStatus?: 'pending' | 'confirmed' | 'cancelled';
}

export interface SaveGuardResult {
  disabled: boolean;
  /** 置灰 Tooltip 文案；可点时为空 */
  tooltip: string;
}

export function saveDisabledReason(input: SaveGuardInput): SaveGuardResult {
  const { terminal, saveable, chartFailed, clarifyStatus } = input;

  if (terminal === 'clarification') {
    return { disabled: true, tooltip: '请先完成口径确认' };
  }
  if (terminal === 'rejection') {
    return { disabled: true, tooltip: '该结果无法保存' };
  }
  if (terminal === 'cancelled' || terminal === 'error') {
    return { disabled: true, tooltip: '取数未成功，无法保存' };
  }
  if (terminal === 'answer' && !saveable) {
    return { disabled: true, tooltip: '暂无数据，无法保存' };
  }
  if (clarifyStatus === 'cancelled') {
    return { disabled: true, tooltip: '请先完成口径确认' };
  }
  if (chartFailed) {
    return { disabled: true, tooltip: '图表加载失败，暂不能保存' };
  }
  if (terminal === null && !saveable) {
    // 报表查看页等无终态上下文：不可保存（页面本就不提供保存入口，防御）
    return { disabled: true, tooltip: '暂无数据，无法保存' };
  }
  return { disabled: false, tooltip: '' };
}
