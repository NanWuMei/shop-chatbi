/**
 * ② 图表区：chart=null 不渲染本区（F18）；右上角切换菜单仅列 switchable，切换纯本地零网络；
 * 渲染异常降级"图表暂不可用"并回调父级（保存置灰），表/解读照常（SDD §3 区2）。
 */
import { Dropdown } from 'antd';
import { BarChartOutlined, LineChartOutlined, PieChartOutlined, RetweetOutlined } from '@ant-design/icons';
import { Component, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { ensureECharts } from '../../../chart/echarts';
import { buildChartOption } from '../../../chart/mapper';
import { CHART_TYPES, type AnswerEvent, type ChartType } from '../../../api/types';

const ICONS: Record<ChartType, ReactNode> = {
  bar: <BarChartOutlined />,
  line: <LineChartOutlined />,
  trend_line: <LineChartOutlined />,
  grouped_bar: <BarChartOutlined />,
  pie: <PieChartOutlined />,
};

const LABELS: Record<ChartType, string> = {
  bar: '柱状图',
  line: '折线图',
  trend_line: '对比趋势线',
  grouped_bar: '分组柱状图',
  pie: '饼图',
};

class ChartErrorBoundary extends Component<{ onFail: () => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    this.props.onFail();
  }
  render() {
    if (this.state.failed) return null;
    return this.props.children;
  }
}

function EChartsBox({ option, onFail }: { option: ReturnType<typeof buildChartOption>; onFail: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const failRef = useRef(onFail);
  failRef.current = onFail;
  useEffect(() => {
    if (!ref.current) return;
    const echarts = ensureECharts();
    let instance: ReturnType<typeof echarts.init> | null = null;
    try {
      instance = echarts.init(ref.current);
      instance.setOption(option);
    } catch {
      instance?.dispose();
      failRef.current();
    }
    return () => instance?.dispose();
  }, [option]);
  return <div ref={ref} style={{ height: 300 }} data-testid="echarts-box" />;
}

export default function ChartView({
  chart,
  rows,
  onChartFailed,
}: {
  chart: NonNullable<AnswerEvent['chart']>;
  rows: AnswerEvent['table']['rows'];
  onChartFailed: () => void;
}) {
  const [currentType, setCurrentType] = useState<ChartType>(chart.type);
  const [failed, setFailed] = useState(false);
  const onFail = useCallback(() => {
    setFailed(true);
    onChartFailed();
  }, [onChartFailed]);

  // 载荷变化（新一轮 answer）时重置本地切换与失败态
  useEffect(() => {
    setCurrentType(chart.type);
    setFailed(false);
  }, [chart]);

  if (failed) {
    return <div className="result-card__chart-failed">图表暂不可用</div>;
  }

  const option = buildChartOption({ ...chart, type: currentType }, rows);
  const switchable = chart.switchable.filter((t): t is ChartType => (CHART_TYPES as readonly string[]).includes(t));

  return (
    <div className="result-card__chart" data-testid="chart-area">
      <div className="result-card__chart-toolbar">
        {switchable.length > 1 && (
          <Dropdown
            menu={{
              items: switchable.map((t) => ({ key: t, icon: ICONS[t], label: LABELS[t] })),
              onClick: ({ key }) => setCurrentType(key as ChartType),
              selectable: true,
              selectedKeys: [currentType],
            }}
          >
            <span role="button" tabIndex={0} data-testid="chart-switch" onClick={(e) => e.preventDefault()}>
              <RetweetOutlined /> {LABELS[currentType]}
            </span>
          </Dropdown>
        )}
      </div>
      <ChartErrorBoundary onFail={onFail}>
        <EChartsBox option={option} onFail={onFail} />
      </ChartErrorBoundary>
    </div>
  );
}
