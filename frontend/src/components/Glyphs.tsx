/** The two glyphs both players use. Same paths, different sizes. */

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
