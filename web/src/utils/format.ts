/**
 * 展示格式化（表/图共用）：千分位、百分比、日期。
 * 只做格式化，不做任何数值计算（NFR-3/AC-21）。
 */

/** "number:2" / "money" / "percent" / "text" 等格式串解析 */
function parseFormat(format: string): { kind: string; digits: number | null } {
  const [kind, digitPart] = format.split(':');
  const digits = digitPart !== undefined && digitPart !== '' ? Number(digitPart) : null;
  return { kind: kind || 'text', digits: digits !== null && Number.isFinite(digits) ? digits : null };
}

function withThousands(text: string): string {
  const [int, ...rest] = text.split('.');
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return rest.length > 0 ? `${grouped}.${rest.join('.')}` : grouped;
}

/** 图表 tooltip 用：仅千分位分组，不改小数（与表格 format 解耦） */
export function formatThousands(value: number): string {
  return withThousands(String(value));
}

/** 表格单元格：数值按 column.format 格式化；rate_delta=null 由调用方给"不可比"（formatValue 返回 null） */
export function formatValue(value: unknown, format: string): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value !== 'number' && typeof value !== 'bigint') return String(value);

  const { kind, digits } = parseFormat(format);
  switch (kind) {
    case 'money':
    case 'number': {
      const d = digits ?? (kind === 'money' ? 2 : 0);
      const fixed = Math.abs(Number(value)).toFixed(d);
      const sign = Number(value) < 0 ? '-' : '';
      return sign + withThousands(fixed);
    }
    case 'percent': {
      const d = digits ?? 1;
      return `${Number(value).toFixed(d)}%`;
    }
    case 'text':
    default:
      return String(value);
  }
}

/** 图表轴/tooltip 数值格式化（与表格同源） */
export function formatChartNumber(value: number, format = 'money'): string {
  return formatValue(value, format);
}

/** 时间显示：ISO → 本地可读；非法原样返回 */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 数据时间范围显示：start~end（可带 label） */
export function formatTimeRange(range: { start: string; end: string; label: string } | null | undefined): string {
  if (!range) return '';
  const span = [range.start, range.end].filter(Boolean).join(' 至 ');
  return range.label ? `${span}（${range.label}）` : span;
}

// ---------------------------------------------------------------------------
// 问题长度预校验（客户端第一道；后端 500 仍兜底）
// ---------------------------------------------------------------------------
export const QUESTION_MAX_LENGTH = 500;
export const TOO_LONG_TIP = '问题过长，请缩短或拆分';

/** 空/超长不可发送；字符按码点计（中文一个字算 1） */
export function questionSendable(text: string): { sendable: boolean; reason: string } {
  const trimmed = text.trim();
  if (trimmed === '') return { sendable: false, reason: '' };
  if ([...trimmed].length > QUESTION_MAX_LENGTH) return { sendable: false, reason: TOO_LONG_TIP };
  return { sendable: true, reason: '' };
}
