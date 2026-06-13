import { useEffect, useState } from "react";

/**
 * Cover / avatar image with a graceful fallback. Many artwork URLs (esp. Cover Art Archive
 * for MusicBrainz) 404 when a release has no art — on error we render a generated cover:
 * a deterministic gradient + the item's initial, so the same album always looks the same.
 *
 * Size and shape come from `className` (the parent sets the box, e.g. "aspect-square w-full"
 * or "h-12 w-12"); `rounded` controls the corner (use "rounded-full" for artists).
 */
function hashHue(seed: string): number {
  let h = 0;
  for (let i = 0; i < seed.length; i += 1) h = (h * 31 + seed.charCodeAt(i)) % 360;
  return h;
}

export default function Artwork({
  src,
  alt,
  seed,
  rounded = "rounded-lg",
  className = "",
}: {
  src?: string | null;
  alt: string;
  seed?: string;
  rounded?: string;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  // Reset the error state if the source changes (e.g. navigating between results).
  useEffect(() => setFailed(false), [src]);

  const show = Boolean(src) && !failed;
  const label = (seed || alt || "?").trim();
  const hue = hashHue(label || "?");
  const initial = (label[0] || "?").toUpperCase();

  return (
    <div
      className={`relative shrink-0 overflow-hidden bg-slate-800 ${rounded} ${className}`}
      style={
        show
          ? undefined
          : {
              background: `linear-gradient(135deg, hsl(${hue} 42% 32%), hsl(${
                (hue + 45) % 360
              } 48% 16%))`,
            }
      }
    >
      {show ? (
        <img
          src={src as string}
          alt={alt}
          loading="lazy"
          onError={() => setFailed(true)}
          className="h-full w-full object-cover"
        />
      ) : (
        // SVG text scales with the box via viewBox, so the initial looks right at any size.
        <svg viewBox="0 0 100 100" className="h-full w-full" aria-hidden>
          <text
            x="50"
            y="54"
            textAnchor="middle"
            dominantBaseline="central"
            fontSize="48"
            fontWeight="700"
            fill="rgba(255,255,255,0.78)"
          >
            {initial}
          </text>
        </svg>
      )}
    </div>
  );
}
