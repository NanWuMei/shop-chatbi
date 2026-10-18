/**
 * chart + rows → ECharts option 纯函数（SDD §6）：
 * - 五型分支：bar / line / trend_line（多系列 line，对比语义）/ grouped_bar（多系列柱）/ pie；
 * - 数字直取 rows，不做任何聚合/计算（NFR-3）；
 * - chart=null 时调用方不得调用本函数（F18）。
 */
import type { EChartsOption } from 'echarts';
import type { AnswerEvent, ChartSpec } from '../api/types';
import { assertNever } from '../api/guard';
import { formatThousands } from '../utils/format';

export function buildChartOption(chart: ChartSpec, rows: AnswerEvent['table']['rows']): EChartsOption {
  const categories = rows.map((r) => String(r[chart.x_field] ?? ''));
  const numeric = (v: unknown): number => (typeof v === 'number' ? v : Number(v) || 0);

  const axisTooltip: EChartsOption['tooltip'] = {
    trigger: 'axis',
    valueFormatter: (value) => (typeof value === 'number' ? formatThousands(value) : String(value ?? '')),
  };

  switch (chart.type) {
    case 'bar':
    case 'grouped_bar': {
      return {
        tooltip: axisTooltip,
        legend: chart.series.length > 1 ? {} : undefined,
        grid: { left: 40, right: 24, top: chart.series.length > 1 ? 36 : 24, bottom: 32 },
        xAxis: { type: 'category', data: categories },
        yAxis: { type: 'value' },
        series: chart.series.map((s) => ({
          name: s.label,
          type: 'bar' as const,
          data: rows.map((r) => numeric(r[s.field])),
        })),
      };
    }
    case 'line':
    case 'trend_line': {
      return {
        tooltip: axisTooltip,
        legend: chart.series.length > 1 ? {} : undefined,
        grid: { left: 40, right: 24, top: chart.series.length > 1 ? 36 : 24, bottom: 32 },
        xAxis: { type: 'category', data: categories },
        yAxis: { type: 'value' },
        series: chart.series.map((s) => ({
          name: s.label,
          type: 'line' as const,
          data: rows.map((r) => numeric(r[s.field])),
        })),
      };
    }
    case 'pie': {
      const series = chart.series[0];
      return {
        tooltip: { trigger: 'item' },
        legend: {},
        series: [
          {
            name: series?.label ?? '',
            type: 'pie' as const,
            radius: '62%',
            data: rows.map((r) => ({
              name: String(r[chart.x_field] ?? ''),
              value: numeric(series ? r[series.field] : undefined),
            })),
          },
        ],
      };
    }
    default:
      return assertNever(chart.type, '未知图型');
  }
}
