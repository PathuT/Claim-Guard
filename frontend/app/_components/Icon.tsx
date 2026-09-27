/** Small inline icon set (24×24, 1.75 stroke, currentColor) — no icon
 * dependency needed for the dozen glyphs the console uses. */

const PATHS: Record<string, string[]> = {
  home: ["M3 10.5 12 3l9 7.5", "M5 9.5V21h14V9.5", "M10 21v-6h4v6"],
  layers: ["M12 3 2 8l10 5 10-5-10-5Z", "m2 13 10 5 10-5", "m2 17.5 10 5 10-5"],
  play: ["M6 4.5v15l13-7.5-13-7.5Z"],
  upload: ["M12 15V3", "m7 8 5-5 5 5", "M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4"],
  inbox: ["M22 12h-6l-2 3h-4l-2-3H2", "M5.5 5h13l3.5 7v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6l3.5-7Z"],
  shield: ["M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z", "m9 12 2 2 4-4"],
  workflow: ["M4 4h6v6H4z", "M14 14h6v6h-6z", "M7 10v4a3 3 0 0 0 3 3h4"],
  check: ["M9 11l3 3L22 4", "M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"],
  activity: ["M22 12h-4l-3 9L9 3l-3 9H2"],
  logout: ["M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4", "m16 17 5-5-5-5", "M21 12H9"],
  external: ["M15 3h6v6", "M10 14 21 3", "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"],
  lock: ["M5 11h14v10H5z", "M8 11V7a4 4 0 0 1 8 0v4"],
  key: ["M15.5 7.5 19 4", "m17 6 2 2", "M11.4 12.6a4.5 4.5 0 1 1-6.36 6.36 4.5 4.5 0 0 1 6.36-6.36Z", "M11.4 12.6 16 8"],
  eye: ["M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z", "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"],
  menu: ["M4 6h16", "M4 12h16", "M4 18h16"],
  x: ["M18 6 6 18", "M6 6l12 12"],
  arrowRight: ["M5 12h14", "m13 6 6 6-6 6"],
  cpu: ["M9 3v2", "M15 3v2", "M9 19v2", "M15 19v2", "M3 9h2", "M3 15h2", "M19 9h2", "M19 15h2", "M6 5h12v14H6z", "M10 9h4v6h-4z"],
  coins: ["M8 7a6 3 0 1 0 12 0A6 3 0 1 0 8 7", "M8 7v4c0 1.66 2.69 3 6 3s6-1.34 6-3V7", "M4 13c0 1.66 2.69 3 6 3", "M4 13v4c0 1.66 2.69 3 6 3 1.3 0 2.5-.2 3.5-.6"],
  alert: ["M12 9v4", "M12 17h.01", "M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"],
  file: ["M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6Z", "M14 3v6h6", "M8 13h8", "M8 17h5"],
  user: ["M20 21a8 8 0 0 0-16 0", "M12 13a5 5 0 1 0 0-10 5 5 0 0 0 0 10Z"],
  spark: ["M12 3v4", "M12 17v4", "M3 12h4", "M17 12h4", "m5.6 5.6 2.8 2.8", "m15.6 15.6 2.8 2.8", "m5.6 18.4 2.8-2.8", "m15.6 8.4 2.8-2.8"],
};

export function Icon({ name, className = "h-4 w-4" }: { name: string; className?: string }) {
  const paths = PATHS[name] ?? PATHS.spark;
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      {paths.map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}

/** The ClaimGuard mark: a shield with a check, in the brand blue. */
export function BrandMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="oklch(0.58 0.16 256)" />
      <path d="M16 6.5 8.5 9.3v6.2c0 5.1 3.3 8.6 7.5 10 4.2-1.4 7.5-4.9 7.5-10V9.3L16 6.5Z" fill="white" fillOpacity="0.95" />
      <path d="m12.4 16.1 2.6 2.6 5-5.2" fill="none" stroke="oklch(0.58 0.16 256)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
