/**
 * 澄清卡（F2/FR-11）：三 input_type 控件、确认前不出数、两轮 round 只显服务端值、
 * suggestions 点选直接发问、取消就地收起不发请求、allow_custom_text 换问法。
 * 卡面绝无数字区域与保存入口（前端铁规则）。
 */
import { Button, DatePicker, Input, Radio, Space, Tag } from 'antd';
import { useState } from 'react';
import type { ClarifyPayload } from '../../api/types';
import type { ClarifySelection } from '../../store/chatStore';

export default function ClarifyCard({
  payload,
  onConfirm,
  onCancel,
  onAskQuestion,
}: {
  payload: ClarifyPayload;
  onConfirm: (selection: ClarifySelection) => void;
  /** 取消：就地收起，不发请求 */
  onCancel: (clarifyId: string) => void;
  /** question_suggestions 点选即发问 */
  onAskQuestion: (question: string) => void;
}) {
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [customRange, setCustomRange] = useState<[string, string] | null>(null);
  const [customText, setCustomText] = useState('');
  const [showCustomText, setShowCustomText] = useState(false);

  // 非进行中澄清（历史还原 confirmed/cancelled）静态呈现，不可交互
  if (payload.status !== 'pending') {
    return (
      <div className="clarify-card clarify-card--closed" data-testid="clarify-card-static">
        {payload.status === 'cancelled' ? '已取消澄清' : '已完成澄清'}
        <span className="clarify-card__title-ref">（{payload.title}）</span>
      </div>
    );
  }

  const canConfirm =
    payload.input_type === 'single_choice'
      ? selectedOption !== null
      : payload.input_type === 'time_quick'
        ? selectedOption !== null || customRange !== null
        : false; // question_suggestions 无确认态：点选即发问

  const confirm = () => {
    if (payload.input_type === 'single_choice' && selectedOption !== null) {
      onConfirm({ type: 'option', value: selectedOption });
      return;
    }
    if (payload.input_type === 'time_quick') {
      if (customRange !== null) {
        onConfirm({ type: 'time_preset', value: { start: customRange[0], end: customRange[1] } });
      } else if (selectedOption !== null) {
        onConfirm({ type: 'time_preset', value: selectedOption });
      }
    }
    // custom 由「换个问法」提交走 confirmCustom
  };

  const confirmCustom = () => {
    const text = customText.trim();
    if (text) onConfirm({ type: 'custom', value: text });
  };

  return (
    <div className="clarify-card" data-testid="clarify-card">
      <div className="clarify-card__head">
        <span className="clarify-card__title">{payload.title}</span>
        <Tag data-testid="clarify-round">澄清轮次 {payload.round}/2</Tag>
      </div>

      {payload.input_type === 'single_choice' && (
        <Radio.Group
          buttonStyle="solid"
          value={selectedOption}
          onChange={(e) => setSelectedOption(e.target.value as string)}
          data-testid="clarify-single-choice"
        >
          {payload.options.map((opt) => (
            <Radio.Button key={opt.value} value={opt.value}>
              {opt.label}
            </Radio.Button>
          ))}
        </Radio.Group>
      )}

      {payload.input_type === 'time_quick' && (
        <Space wrap data-testid="clarify-time-quick">
          {payload.options.map((opt) => (
            <Button
              key={opt.value}
              type={selectedOption === opt.value && customRange === null ? 'primary' : 'default'}
              onClick={() => {
                setSelectedOption(opt.value);
                setCustomRange(null);
              }}
            >
              {opt.label}
            </Button>
          ))}
          <Button
            type={customRange !== null ? 'primary' : 'default'}
            onClick={() => {
              setSelectedOption(null);
              setCustomRange(customRange ?? ['', '']);
            }}
          >
            自定义
          </Button>
        </Space>
      )}
      {payload.input_type === 'time_quick' && customRange !== null && (
        <DatePicker.RangePicker
          data-testid="clarify-time-range"
          onChange={(_, strs) => setCustomRange([strs[0] || '', strs[1] || ''])}
        />
      )}

      {payload.input_type === 'question_suggestions' && (
        <Space direction="vertical" data-testid="clarify-suggestions">
          {payload.suggestions.map((s) => (
            <Button key={s.question} onClick={() => onAskQuestion(s.question)}>
              {s.question}
            </Button>
          ))}
        </Space>
      )}

      {payload.allow_custom_text && payload.input_type !== 'question_suggestions' && (
        <div className="clarify-card__custom">
          {!showCustomText ? (
            <Button type="link" onClick={() => setShowCustomText(true)}>
              我换个问法
            </Button>
          ) : (
            <Space.Compact style={{ width: '100%' }}>
              <Input
                value={customText}
                placeholder="输入新的问法"
                onChange={(e) => setCustomText(e.target.value)}
                onPressEnter={confirmCustom}
                data-testid="clarify-custom-input"
              />
              <Button type="primary" disabled={customText.trim() === ''} onClick={confirmCustom}>
                提交问法
              </Button>
            </Space.Compact>
          )}
        </div>
      )}

      <div className="clarify-card__actions">
        {payload.input_type !== 'question_suggestions' && (
          <Button type="primary" disabled={!canConfirm} onClick={confirm} data-testid="clarify-confirm">
            确认并查询
          </Button>
        )}
        <Button onClick={() => onCancel(payload.clarify_id)} data-testid="clarify-cancel">
          取消
        </Button>
      </div>
    </div>
  );
}
