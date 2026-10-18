/** 用户气泡（乐观渲染）。 */
export default function UserBubble({ question }: { question: string }) {
  return (
    <div className="user-bubble" data-testid="user-bubble">
      {question}
    </div>
  );
}
