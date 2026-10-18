import { describe, expect, it } from 'vitest';
import { assertNever } from '../api/guard';
import {
  TERMINAL_EVENTS,
  STAGES,
  CHART_TYPES,
  CLARIFY_INPUT_TYPES,
  CLARIFY_REASON_CODES,
  REJECTION_REASON_CODES,
  MESSAGE_TYPES,
  type TerminalEvent,
} from '../api/types';
import {
  answerBar,
  answerEmpty,
  answerLine,
  answerComparison,
  answerGroupedBar,
  answerPie,
  clarifySingleChoice,
  clarifyTimeQuick,
  clarifyQuestionSuggestions,
  clarifyAnaphora,
  rejectionNotDataQuestion,
  rejectionNoMatchingData,
  rejectionCaliberConflict,
  rejectionGenLintExhausted,
  rejectionQueryTimeout,
  rejectionQueryError,
  errorLlmUnavailable,
  httpErrorValidation,
  httpErrorNameConflict,
  reportDetail,
  reportListItems,
  refreshAnswer,
  refreshEmptyAnswer,
  refreshQueryTimeout,
  refreshQueryGenFailed,
  sessionListItems,
  sessionMessages,
  type SseFrame,
} from './fixtures';

/** 穷尽性守卫示例：新增 TerminalEvent 成员而不加分支时，此 switch 编译失败（AC-1/TR-2.1）。 */
function terminalLabel(t: TerminalEvent): string {
  switch (t) {
    case 'answer':
      return '结果';
    case 'clarification':
      return '澄清';
    case 'rejection':
      return '拒答';
    case 'error':
      return '错误';
    case 'cancelled':
      return '已取消';
    default:
      return assertNever(t, '终态事件未穷尽');
  }
}

describe('api/types 枚举契约', () => {
  it('五图型不含旧术语且 chart 可 null（fixture 留证）', () => {
    expect(CHART_TYPES).toEqual(['bar', 'line', 'trend_line', 'grouped_bar', 'pie']);
    expect(answerEmpty.chart).toBeNull();
  });

  it('stage 三值 / 终态五值 / 消息五型 / 澄清四码三控件 / 拒答六码', () => {
    expect(STAGES).toEqual(['understanding', 'checking_caliber', 'querying']);
    expect(TERMINAL_EVENTS).toEqual(['answer', 'clarification', 'rejection', 'error', 'cancelled']);
    expect(MESSAGE_TYPES).toEqual(['user', 'clarification', 'answer', 'rejection', 'note']);
    expect(CLARIFY_REASON_CODES).toEqual(['METRIC_DIM_AMBIGUOUS', 'MISSING_TIME', 'VAGUE', 'ANAPHORA_UNRESOLVED']);
    expect(CLARIFY_INPUT_TYPES).toEqual(['single_choice', 'time_quick', 'question_suggestions']);
    expect(REJECTION_REASON_CODES).toHaveLength(6);
  });

  it('穷尽 switch 覆盖全部终态且守卫可用', () => {
    expect(TERMINAL_EVENTS.map(terminalLabel)).toEqual(['结果', '澄清', '拒答', '错误', '已取消']);
    expect(() => assertNever(undefined as never)).toThrow();
  });

  it('对比载荷 rate_delta=null（不可比）且 delta 为字符串', () => {
    expect(answerComparison.comparison?.changes).toContainEqual({
      key: '渠道 C',
      value_delta: '76543210.00',
      rate_delta: null,
    });
  });

  it('空结果 saveable=false 且 rows=[]', () => {
    expect(answerEmpty.table.rows).toHaveLength(0);
    expect(answerEmpty.saveable).toBe(false);
  });
});

describe('契约 fixtures 类型一致性（TR-2.3，编译即校验）', () => {
  it('五图型样例齐备', () => {
    expect([answerBar, answerLine, answerComparison, answerGroupedBar, answerPie].map((a) => a.chart?.type)).toEqual(
      ['bar', 'line', 'trend_line', 'grouped_bar', 'pie'],
    );
  });

  it('澄清四码 × 三控件样例齐备', () => {
    expect(
      [clarifySingleChoice, clarifyTimeQuick, clarifyQuestionSuggestions, clarifyAnaphora].map(
        (c) => `${c.reason_code}:${c.input_type}`,
      ),
    ).toEqual([
      'METRIC_DIM_AMBIGUOUS:single_choice',
      'MISSING_TIME:time_quick',
      'VAGUE:question_suggestions',
      'ANAPHORA_UNRESOLVED:single_choice',
    ]);
  });

  it('拒答六码样例齐备', () => {
    expect(
      [
        rejectionNotDataQuestion,
        rejectionNoMatchingData,
        rejectionCaliberConflict,
        rejectionGenLintExhausted,
        rejectionQueryTimeout,
        rejectionQueryError,
      ].map((r) => r.reason_code),
    ).toEqual([...REJECTION_REASON_CODES]);
    expect(errorLlmUnavailable.retryable).toBe(true);
  });

  it('SSE 帧序列含同段重复帧供去重测试', () => {
    const frames: SseFrame[] = [
      { event: 'stage', data: { stage: 'understanding', label: 'x' } },
      { event: 'stage', data: { stage: 'understanding', label: 'x' } },
      { event: 'done', data: { turn_id: 't' } },
    ];
    expect(frames.filter((f) => f.event === 'stage')).toHaveLength(2);
  });

  it('错误信封 / 报表 / 会话样例形状正确', () => {
    expect(httpErrorValidation.error.code).toBe('E_VALIDATION');
    expect(httpErrorNameConflict.error.existing?.id).toBe('report-0001');
    expect(reportListItems).toHaveLength(2);
    expect(reportDetail.snapshot.chart?.type).toBe('bar');
    expect([refreshAnswer, refreshEmptyAnswer, refreshQueryTimeout, refreshQueryGenFailed].map((r) => r.action)).toEqual(
      ['answer', 'answer', 'query_failed', 'query_gen_failed'],
    );
    expect(sessionListItems[0].message_count).toBeGreaterThan(0);
    const types = sessionMessages.messages.map((m) => m.type);
    expect(types).toEqual(expect.arrayContaining(['user', 'clarification', 'answer', 'rejection', 'note']));
  });
});

describe('全仓旧术语静态扫描（TR-2.2 / F2）', () => {
  it('src 下无 narrative、dual_line 残留', () => {
    const modules = import.meta.glob('/src/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
    const offenders = Object.entries(modules)
      .filter(([, text]) => new RegExp(`nar${'rative'}|dual${'_line'}`).test(text))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });
});
