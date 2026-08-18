/** The small marks the interface reuses: the players' two, and download. */

interface Props {
  size?: number;
}

export function PlayGlyph({ size = 16 }: Props) {
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" aria-hidden="true">
      <path d="M5 3.2v11.6L14.4 9 5 3.2z" fill="currentColor" />
    </svg>
  );
}

export function PauseGlyph({ size = 16 }: Props) {
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" aria-hidden="true">
      <path d="M5 3.5h3.1v11H5zM9.9 3.5H13v11H9.9z" fill="currentColor" />
    </svg>
  );
}

/** Download, wherever something can be saved: the same mark every time. */
export function DownGlyph() {
  return (
    <svg className="filepill__down" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      <path
        d="M6 1.6v6.2M3.4 5.6 6 8.2l2.6-2.6M2.2 10.4h7.6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
