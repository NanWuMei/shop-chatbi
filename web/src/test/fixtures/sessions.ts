import type { SessionMessagesResponse, SessionSummary } from '../../api/types';
import { answerBar, answerEmpty } from './answers';
import { clarifySingleChoice, rejectionQueryTimeout } from './chat';

export const sessionListItems: SessionSummary[] = [
  {
    id: 'session-0002',
    title: '618 大促各渠道 GMV 同比',
    message_count: 4,
    last_question_at: '2026-10-17T11:30:00Z',
    created_at: '2026-10-17T11:28:00Z',
  },
  {
    id: 'session-0001',
    title: '618 大促期间各渠道 GMV，按从高到低排',
    message_count: 5,
    last_question_at: '2026-10-17T10:10:00Z',
    created_at: '2026-10-17T10:00:00Z',
  },
];

/** 五 type 全覆盖：user/clarification/answer/rejection/note；answer 再分空/非空 */
export const sessionMessages: SessionMessagesResponse = {
  session: sessionListItems[1],
  messages: [
    {
      id: 'msg-01',
      seq: 1,
      type: 'user',
      created_at: '2026-10-17T10:00:00Z',
      payload: { question: '618 大促期间各渠道 GMV，按从高到低排' },
    },
    {
      id: 'msg-02',
      seq: 2,
      type: 'clarification',
      created_at: '2026-10-17T10:00:05Z',
      payload: clarifySingleChoice,
    },
    {
      id: 'msg-03',
      seq: 3,
      type: 'answer',
      created_at: '2026-10-17T10:01:00Z',
      payload: answerBar,
    },
    {
      id: 'msg-04',
      seq: 4,
      type: 'user',
      created_at: '2026-10-17T10:05:00Z',
      payload: { question: '那海外渠道呢' },
    },
    {
      id: 'msg-05',
      seq: 5,
      type: 'answer',
      created_at: '2026-10-17T10:05:30Z',
      payload: answerEmpty,
    },
    {
      id: 'msg-06',
      seq: 6,
      type: 'user',
      created_at: '2026-10-17T10:08:00Z',
      payload: { question: '为什么海外没有数据' },
    },
    {
      id: 'msg-07',
      seq: 7,
      type: 'rejection',
      created_at: '2026-10-17T10:08:10Z',
      payload: rejectionQueryTimeout,
    },
    {
      id: 'msg-08',
      seq: 8,
      type: 'note',
      created_at: '2026-10-17T10:09:00Z',
      payload: { kind: 'cancelled', text: '已取消' },
    },
  ],
};
