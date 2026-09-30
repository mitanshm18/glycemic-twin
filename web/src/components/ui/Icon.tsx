/**
 * One small icon set, drawn on a 16px grid with 1.5px strokes so every glyph has the same weight.
 * Icons are decorative (aria-hidden) unless a label is given.
 */

import type { SVGProps } from "react";

const PATHS = {
  patients: "M5.5 7a2.25 2.25 0 1 0 0-4.5 2.25 2.25 0 0 0 0 4.5ZM1.5 13.5c0-2.2 1.8-3.75 4-3.75s4 1.55 4 3.75M11 6.75a1.9 1.9 0 1 0 0-3.8M12.25 9.75c1.35.35 2.25 1.5 2.25 3.25",
  model: "M2.5 13.5h11M4 11V8M7 11V4.5M10 11V6.5M13 11V2.5",
  sun: "M8 10.75a2.75 2.75 0 1 0 0-5.5 2.75 2.75 0 0 0 0 5.5ZM8 1v1.25M8 13.75V15M1 8h1.25M13.75 8H15M3.05 3.05l.9.9M12.05 12.05l.9.9M3.05 12.95l.9-.9M12.05 3.95l.9-.9",
  moon: "M13.5 9.6A5.75 5.75 0 0 1 6.4 2.5a5.75 5.75 0 1 0 7.1 7.1Z",
  monitor: "M2 3h12v8H2zM6 14h4M8 11v3",
  search: "M7 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10ZM14 14l-3.4-3.4",
  eye: "M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8ZM8 10a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z",
  eyeOff: "M6.6 3.65A6.7 6.7 0 0 1 8 3.5c4 0 6.5 4.5 6.5 4.5a11.6 11.6 0 0 1-1.7 2.2M10.1 10.9A6.4 6.4 0 0 1 8 12.5C4 12.5 1.5 8 1.5 8a11.4 11.4 0 0 1 2.6-3.1M6.6 6.6a2 2 0 0 0 2.8 2.8M2 2l12 12",
  chevronRight: "M6 3.5 10.5 8 6 12.5",
  chevronLeft: "M10 3.5 5.5 8 10 12.5",
  chevronDown: "M3.5 6 8 10.5 12.5 6",
  arrowUp: "M8 13V3M3.75 7.25 8 3l4.25 4.25",
  arrowDown: "M8 3v10M3.75 8.75 8 13l4.25-4.25",
  arrowRight: "M3 8h10M8.75 3.75 13 8l-4.25 4.25",
  sortAsc: "M8 12.5v-9M4.5 7 8 3.5 11.5 7",
  sortDesc: "M8 3.5v9M4.5 9 8 12.5 11.5 9",
  sortNone: "M5 6l3-3 3 3M5 10l3 3 3-3",
  dash: "M4 8h8",
  copy: "M5.5 5.5V3a1 1 0 0 1 1-1H13a1 1 0 0 1 1 1v6.5a1 1 0 0 1-1 1h-2.5M3 5.5h6.5a1 1 0 0 1 1 1V13a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V6.5a1 1 0 0 1 1-1Z",
  check: "M3 8.5 6.25 11.75 13 5",
  x: "M4 4l8 8M12 4l-8 8",
  alert: "M8 5.5v3.25M8 11v.25M7.1 2.5 1.6 12a1 1 0 0 0 .86 1.5h11.08a1 1 0 0 0 .86-1.5L8.9 2.5a1.04 1.04 0 0 0-1.8 0Z",
  info: "M8 14.5a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13ZM8 7.25v4M8 4.75V5",
  clock: "M8 14.5a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13ZM8 4.5V8l2.5 1.5",
  layers: "M8 1.75 14.25 5 8 8.25 1.75 5 8 1.75ZM1.75 8 8 11.25 14.25 8M1.75 11 8 14.25 14.25 11",
  fingerprint: "M4.5 13.5c.8-1.4 1.25-3.1 1.25-5a2.25 2.25 0 1 1 4.5 0c0 .6 0 1.2-.1 1.8M8 8.5c0 2.4-.6 4.3-1.6 5.8M2.6 11c.4-.8.65-1.7.65-2.75a4.75 4.75 0 0 1 9.5 0c0 1.9-.3 3.5-.9 4.9M11.9 3.4A6 6 0 0 0 2.25 6.2",
  menu: "M2.5 4.5h11M2.5 8h11M2.5 11.5h11",
  logout: "M6 14H3.5a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1H6M10.5 11.25 13.75 8 10.5 4.75M13.75 8H6",
  play: "M4.5 3v10l8.5-5-8.5-5Z",
  pause: "M5.5 3.5v9M10.5 3.5v9",
  rotate: "M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v3h-3",
  record: "M3.5 2.5h9v11h-9zM5.75 5.5h4.5M5.75 8h4.5M5.75 10.5h2.5",
  flask: "M6.25 1.75h3.5M6.75 1.75v4.5L2.6 12.9a.9.9 0 0 0 .77 1.35h9.26a.9.9 0 0 0 .77-1.35L9.25 6.25v-4.5M4.4 10h7.2",
  shield: "M8 1.75 13.25 3.5v4.25c0 3.1-2.2 5.7-5.25 6.5-3.05-.8-5.25-3.4-5.25-6.5V3.5L8 1.75Z",
  meal: "M4.25 1.75v4.5a1.75 1.75 0 0 0 3.5 0v-4.5M6 7.9v6.35M11.25 14.25V1.75c-1.5 0-2.5 1.75-2.5 4.5 0 1.5.8 2.25 2.5 2.25",
  target: "M8 14.5a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13ZM8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM8 8.25v-.5",
  pulse: "M1.5 8.5h3l1.75-4 3 8 1.75-4h3.5",
  external: "M9.5 2.5h4v4M13.5 2.5 7.75 8.25M12 9.5v3a1 1 0 0 1-1 1H3.5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h3",
  sliders: "M3 13.5V9M3 6.5V2.5M8 13.5V8M8 5.5V2.5M13 13.5V10.5M13 8V2.5M1.5 9h3M6.5 5.5h3M11.5 10.5h3",
  history: "M1.75 8a6.25 6.25 0 1 0 1.9-4.5M1.75 1.75V4.5H4.5M8 4.75V8l2.25 1.25",
} as const;

export type IconName = keyof typeof PATHS;

interface Props extends Omit<SVGProps<SVGSVGElement>, "name"> {
  name: IconName;
  size?: number;
  label?: string;
}

export function Icon({ name, size = 16, label, ...rest }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={label ? undefined : true}
      role={label ? "img" : undefined}
      aria-label={label}
      focusable="false"
      {...rest}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
