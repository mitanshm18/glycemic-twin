import type { ReactNode } from "react";
import { cx } from "@/lib/cx";

interface Props {
  id: string;
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}

/** A workspace section: a heading with a hairline above, not a card. */
export function Section({ id, eyebrow, title, description, aside, children, className }: Props) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className={cx("section", className)}>
      <header className="section__head">
        <div>
          {eyebrow && <span className="section__eyebrow">{eyebrow}</span>}
          <h2 id={`${id}-title`} className="section__title">
            {title}
          </h2>
          {description && <p className="section__desc">{description}</p>}
        </div>
        {aside && <div className="section__aside">{aside}</div>}
      </header>
      {children}
    </section>
  );
}
