/* Original flat illustrations (no third-party artwork). Each cover = one device motif on a
 * coloured field; shared language: traces, pads and vias of a PCB. */

type CoverProps = { title: string };

function Frame({ bg, children, title }: { bg: string; children: React.ReactNode; title: string }) {
  return (
    <svg viewBox="0 0 160 96" role="img" aria-label={title} className="block h-full w-full">
      <rect width="160" height="96" fill={bg} />
      {children}
    </svg>
  );
}

export function EcgCover({ title }: CoverProps) {
  return (
    <Frame bg="#12503f" title={title}>
      <path
        d="M0 60h40l8-22 10 44 9-34 6 12h87"
        fill="none"
        stroke="#9fe3c6"
        strokeWidth="4"
        strokeLinejoin="round"
      />
      <circle cx="132" cy="24" r="10" fill="#f4f5f2" />
      <circle cx="132" cy="24" r="4" fill="#12503f" />
      <path d="M0 84h160" stroke="#2c7a62" strokeWidth="2" strokeDasharray="4 6" />
    </Frame>
  );
}

export function EegCover({ title }: CoverProps) {
  return (
    <Frame bg="#2a1f6e" title={title}>
      {[22, 40, 58, 76].map((y, i) => (
        <path
          key={y}
          d={`M0 ${y} q10 -${6 + i * 2} 20 0 t20 0 t20 0 t20 0 t20 0 t20 0 t20 0 t20 0`}
          fill="none"
          stroke={["#c9bdfd", "#8f7bf0", "#f4f5f2", "#8f7bf0"][i]}
          strokeWidth="2.5"
        />
      ))}
    </Frame>
  );
}

export function Spo2Cover({ title }: CoverProps) {
  return (
    <Frame bg="#f2d7c9" title={title}>
      <rect x="44" y="18" width="72" height="60" rx="18" fill="#b42f25" />
      <rect x="56" y="30" width="48" height="36" rx="10" fill="#f4f5f2" />
      <text
        x="80"
        y="55"
        textAnchor="middle"
        fontFamily="IBM Plex Mono"
        fontSize="15"
        fill="#15181e"
      >
        98%
      </text>
      <circle cx="132" cy="22" r="6" fill="#15181e" />
      <circle cx="28" cy="74" r="6" fill="#15181e" />
    </Frame>
  );
}

export function InfusionCover({ title }: CoverProps) {
  return (
    <Frame bg="#dfe9f6" title={title}>
      <rect x="62" y="10" width="36" height="46" rx="6" fill="#1d4f91" />
      <path d="M80 56v18" stroke="#1d4f91" strokeWidth="4" />
      <path d="M80 78c-6 8-6 12 0 14 6-2 6-6 0-14z" fill="#5b3fd0" />
      <path
        d="M10 30h40M110 30h40M10 66h40M110 66h40"
        stroke="#9db6dc"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </Frame>
  );
}

export function BlankCover({ title }: CoverProps) {
  return (
    <svg viewBox="0 0 160 96" role="img" aria-label={title} className="block h-full w-full">
      <rect width="160" height="96" fill="#f4f5f2" />
      <path d="M80 34v28M66 48h28" stroke="#15181e" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function GuideArt({ variant }: { variant: 1 | 2 | 3 }) {
  if (variant === 1)
    return (
      <svg viewBox="0 0 320 140" aria-hidden className="h-full w-full">
        <rect width="320" height="140" fill="#e3f0ea" />
        <rect x="40" y="26" width="120" height="88" rx="8" fill="#12503f" />
        {[0, 1, 2, 3].map((i) => (
          <rect key={i} x={54 + i * 26} y="40" width="14" height="14" rx="3" fill="#9fe3c6" />
        ))}
        <path d="M160 70h70l20-20h40" fill="none" stroke="#12503f" strokeWidth="4" />
        <circle cx="290" cy="50" r="8" fill="#15181e" />
      </svg>
    );
  if (variant === 2)
    return (
      <svg viewBox="0 0 320 140" aria-hidden className="h-full w-full">
        <rect width="320" height="140" fill="#efebfd" />
        {[0, 1, 2, 3, 4].map((i) => (
          <rect key={`a${i}`} x={30 + i * 54} y="34" width="44" height="22" rx="5" fill="#5b3fd0" />
        ))}
        {[0, 1, 2, 3, 4].map((i) => (
          <rect
            key={`b${i}`}
            x={30 + i * 54}
            y="84"
            width="44"
            height="22"
            rx="5"
            fill={i === 2 ? "#5b3fd0" : "#12503f"}
          />
        ))}
      </svg>
    );
  return (
    <svg viewBox="0 0 320 140" aria-hidden className="h-full w-full">
      <rect width="320" height="140" fill="#e6eefa" />
      {[0, 1, 2].map((i) => (
        <g key={i} transform={`translate(60 ${28 + i * 32})`}>
          <rect
            width="22"
            height="22"
            rx="5"
            fill={i === 1 ? "#1d4f91" : "#ffffff"}
            stroke="#1d4f91"
            strokeWidth="2.5"
          />
          <rect x="36" y="7" width={140 - i * 30} height="8" rx="4" fill="#9db6dc" />
        </g>
      ))}
    </svg>
  );
}
