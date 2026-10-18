/**
 * ECharts 按需注册（SDD §1/§6）：仅 bar/line/pie 系列 + 必要组件。
 * trend_line 与 line 共用 line 系列，grouped_bar 共用 bar 系列。
 */
import * as echarts from 'echarts/core';
import { BarChart, LineChart, PieChart } from 'echarts/charts';
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

let registered = false;

export function ensureECharts(): typeof echarts {
  if (!registered) {
    echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);
    registered = true;
  }
  return echarts;
}
