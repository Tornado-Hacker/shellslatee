import DOMPurify from "dompurify";
import { marked } from "marked";
import { useEffect, useMemo, useRef } from "react";
import { slugify } from "@/lib/utils";
import { cn } from "@/lib/utils";

marked.setOptions({ gfm: true, breaks: false });

export function Markdown({
  markdown,
  className,
  onHeading,
  onTimestamp,
}: {
  markdown: string;
  className?: string;
  onHeading?: (headings: { id: string; text: string; level: number }[]) => void;
  onTimestamp?: (start: number) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const html = useMemo(() => DOMPurify.sanitize(marked.parse(markdown) as string), [markdown]);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const headings: { id: string; text: string; level: number }[] = [];
    node.querySelectorAll("h1,h2,h3").forEach((heading) => {
      const text = heading.textContent ?? "";
      const id = heading.id || slugify(text);
      heading.id = id;
      headings.push({ id, text, level: Number(heading.tagName.slice(1)) });
    });
    onHeading?.(headings);
  }, [html, onHeading]);

  return (
    <div
      ref={ref}
      className={cn("markdown", className)}
      onClick={(event) => {
        const anchor = (event.target as HTMLElement).closest("a");
        if (!anchor) return;
        const href = anchor.getAttribute("href") ?? "";
        const stamp = /[#&?]t=(\d+(?:\.\d+)?)/.exec(href);
        if (stamp && onTimestamp) {
          event.preventDefault();
          onTimestamp(Number(stamp[1]));
          return;
        }
        if (href.startsWith("file://")) event.preventDefault();
      }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
