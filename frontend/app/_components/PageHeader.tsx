/** Consistent page heading: eyebrow, title, one-paragraph description and
 * optional actions on the right. */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0 max-w-4xl">
        {eyebrow && <p className="text-xs font-semibold uppercase tracking-[0.12em] text-chart-1">{eyebrow}</p>}
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground sm:text-[28px]">{title}</h1>
        {description && <div className="mt-2 text-sm leading-relaxed text-muted-foreground">{description}</div>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
