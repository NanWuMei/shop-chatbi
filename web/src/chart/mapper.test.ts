import { describe, expect, it } from 'vitest';
import { buildChartOption } from './mapper';
import { answerBar, answerComparison, answerEmpty, answerGroupedBar, answerLine, answerPie } from '../test/fixtures';

/** mapper 五型结构映射（AC-9/AC-21：结构映射零计算） */
describe('buildChartOption 五图型', () => {
  it('bar：单系列柱状，类目取 x_field', () => {
    const opt = buildChartOption(answerBar.chart!, answerBar.table.rows);
    expect(opt.xAxis).toMatchObject({ type: 'category', data: ['渠道 A', '渠道 B', '渠道 C'] });
    expect(opt.series).toEqual([
      { name: 'GMV（元）', type: 'bar', data: [120345678.9, 98765432.1, 76543210] },
    ]);
  });

  it('line：折线', () => {
    const opt = buildChartOption(answerLine.chart!, answerLine.table.rows);
    expect(opt.series).toEqual([{ name: 'GMV（元）', type: 'line', data: [8100000, 9200000, 8800000] }]);
  });

  it('trend_line：多系列 line（对比语义）', () => {
    const opt = buildChartOption(answerComparison.chart!, answerComparison.table.rows);
    expect(opt.series).toEqual([
      { name: '本期 GMV（元）', type: 'line', data: [120345678.9, 98765432.1, 76543210] },
      { name: '去年同期 GMV（元）', type: 'line', data: [101643200, 88123456, 0] },
    ]);
  });

  it('grouped_bar：多系列柱', () => {
    const opt = buildChartOption(answerGroupedBar.chart!, answerGroupedBar.table.rows);
    expect(opt.series).toEqual([
      { name: '本期 GMV（元）', type: 'bar', data: [120345678.9, 98765432.1, 76543210] },
      { name: '去年同期 GMV（元）', type: 'bar', data: [101643200, 88123456, 0] },
    ]);
  });

  it('pie：name/value 结构', () => {
    const opt = buildChartOption(answerPie.chart!, answerPie.table.rows);
    expect(opt.series).toEqual([
      {
        name: 'GMV（元）',
        type: 'pie',
        radius: '62%',
        data: [
          { name: '渠道 A', value: 120345678.9 },
          { name: '渠道 B', value: 98765432.1 },
          { name: '渠道 C', value: 76543210 },
        ],
      },
    ]);
  });

  it('空结果 rows=[] 时 mapper 不被调用（chart=null 由上层保证）', () => {
    expect(answerEmpty.chart).toBeNull();
  });
});
