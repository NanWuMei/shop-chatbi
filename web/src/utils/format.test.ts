import { describe, expect, it } from 'vitest';
import {
  QUESTION_MAX_LENGTH,
  formatDateTime,
  formatThousands,
  formatTimeRange,
  formatValue,
  questionSendable,
} from './format';

describe('formatValue（AC-8/AC-21）', () => {
  it('money 两位小数千分位', () => {
    expect(formatValue(120345678.9, 'money')).toBe('120,345,678.90');
    expect(formatValue(1234567, 'money')).toBe('1,234,567.00');
    expect(formatValue(-9876543.21, 'money')).toBe('-9,876,543.21');
  });

  it('number 默认 0 位、number:2 两位', () => {
    expect(formatValue(1234567, 'number')).toBe('1,234,567');
    expect(formatValue(1234.567, 'number:2')).toBe('1,234.57');
  });

  it('percent 一位小数带 %', () => {
    expect(formatValue(18.3, 'percent')).toBe('18.3%');
    expect(formatValue(12.34, 'percent:2')).toBe('12.34%');
  });

  it('text 原样', () => {
    expect(formatValue('渠道 A', 'text')).toBe('渠道 A');
  });

  it('null 返回空串（不可比文案由 DataTable 层负责）', () => {
    expect(formatValue(null, 'percent')).toBe('');
    expect(formatValue(undefined, 'money')).toBe('');
  });
});

describe('formatThousands（图表 tooltip，不改小数）', () => {
  it('整数与带小数分组正确', () => {
    expect(formatThousands(1234567)).toBe('1,234,567');
    expect(formatThousands(1234567.89)).toBe('1,234,567.89');
  });
});

describe('formatDateTime / formatTimeRange', () => {
  it('ISO → 本地可读', () => {
    expect(formatDateTime('2026-10-17T10:05:00Z')).toMatch(/2026-10-17 \d{2}:\d{2}/);
  });

  it('非法输入原样返回', () => {
    expect(formatDateTime('not-a-date')).toBe('not-a-date');
    expect(formatDateTime(null)).toBe('');
  });

  it('时间范围带 label', () => {
    expect(formatTimeRange({ start: '2026-06-01', end: '2026-06-20', label: '618 大促期' })).toBe(
      '2026-06-01 至 2026-06-20（618 大促期）',
    );
    expect(formatTimeRange({ start: 'a', end: 'b', label: '' })).toBe('a 至 b');
    expect(formatTimeRange(null)).toBe('');
  });
});

describe('questionSendable 长度预校验（AC-3/F9）', () => {
  it('空/纯空白不可发送', () => {
    expect(questionSendable('').sendable).toBe(false);
    expect(questionSendable('   ').sendable).toBe(false);
  });

  it('恰好 500 字可发送', () => {
    const q = '好'.repeat(QUESTION_MAX_LENGTH);
    expect(questionSendable(q).sendable).toBe(true);
  });

  it('501 字不可发送且固定提示', () => {
    const result = questionSendable('好'.repeat(QUESTION_MAX_LENGTH + 1));
    expect(result.sendable).toBe(false);
    expect(result.reason).toBe('问题过长，请缩短或拆分');
  });
});
