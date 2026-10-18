/** ① 一句解读：单行原样渲染 insight，不改写、不追加（SDD §3 ResultCard 区1）。 */
export default function Insight({ text }: { text: string }) {
  return (
    <p className="result-card__insight" data-testid="insight">
      {text}
    </p>
  );
}
