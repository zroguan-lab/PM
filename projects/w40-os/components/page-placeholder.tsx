type PagePlaceholderProps = { label: string; title: string; description: string };

export function PagePlaceholder({ label, title, description }: PagePlaceholderProps) {
  return (
    <section className="page-placeholder">
      <header className="page-header"><p className="eyebrow">{label}</p><h1>{title}</h1><p>{description}</p></header>
      <div className="placeholder-surface"><span>PHASE 1 / STRUCTURE READY</span><p>页面内容将在对应阶段实现</p></div>
    </section>
  );
}
