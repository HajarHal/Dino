// Icônes au trait (24 × 24, couleur du texte). Aucune image externe, aucun emoji.
import type { ReactNode } from "react";

function Svg({ children, size = 24, title }: { children: ReactNode; size?: number; title?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden={title ? undefined : true} role={title ? "img" : undefined}>
      {title && <title>{title}</title>}
      {children}
    </svg>
  );
}
type P = { size?: number };

export const Shield = (p: P) => <Svg {...p}><path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3z" /><path d="M9 12l2 2 4-4" /></Svg>;
export const Doc = (p: P) => <Svg {...p}><path d="M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></Svg>;
export const Dots = (p: P) => <Svg {...p}><circle cx="5" cy="12" r="1.2" /><circle cx="12" cy="12" r="1.2" /><circle cx="19" cy="12" r="1.2" /></Svg>;
export const Wheel = (p: P) => <Svg {...p}><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="2" /><path d="M12 3.5V10M4 14l6.2-1.3M20 14l-6.2-1.3" /></Svg>;
export const Glass = (p: P) => <Svg {...p}><path d="M4 16c1-6 4-9 8-9s7 3 8 9H4z" /><path d="M10 9.5l-1.5 3 2 1-1 2.5M15 11l-1.2 2" /></Svg>;
export const Key = (p: P) => <Svg {...p}><circle cx="8" cy="14" r="4" /><path d="M11 11l8-8M16 6l2 2M14 8l2 2" /></Svg>;
export const Flame = (p: P) => <Svg {...p}><path d="M12 21c-3.9 0-6.5-2.6-6.5-6 0-3.6 3-5.6 4-9 2 1.5 2.5 3.5 2.5 5 1-.6 1.8-1.8 2-3 2 1.8 4.5 4.3 4.5 7 0 3.4-2.6 6-6.5 6z" /></Svg>;
export const Storm = (p: P) => <Svg {...p}><path d="M7 16a4.5 4.5 0 0 1-.6-9A6 6 0 0 1 18 8a4 4 0 0 1-1 8" /><path d="M12.5 12l-2 4h3l-2 4" /></Svg>;
export const Users = (p: P) => <Svg {...p}><circle cx="9" cy="8" r="3.2" /><path d="M3 20c.5-3.5 3-5.5 6-5.5s5.5 2 6 5.5" /><path d="M16 5.2a3 3 0 0 1 0 5.6M18 14.8c1.7.7 2.8 2.5 3 5.2" /></Svg>;
export const Tow = (p: P) => <Svg {...p}><path d="M3 16V9h7l2 4h5l3 3v1H3z" /><circle cx="7" cy="17.5" r="1.8" /><circle cx="16.5" cy="17.5" r="1.8" /><path d="M10 9l5-5M15 4v3" /></Svg>;
export const Scale = (p: P) => <Svg {...p}><path d="M12 4v16M7 20h10M5 7h14M5 7l-2.5 6a3 3 0 0 0 5 0L5 7zM19 7l-2.5 6a3 3 0 0 0 5 0L19 7z" /></Svg>;
export const Chevron = (p: P) => <Svg {...p}><path d="M9 6l6 6-6 6" /></Svg>;
export const Back = (p: P) => <Svg {...p}><path d="M15 6l-6 6 6 6" /></Svg>;
export const Close = (p: P) => <Svg {...p}><path d="M6 6l12 12M18 6L6 18" /></Svg>;
export const Check = (p: P) => <Svg {...p}><path d="M5 12.5l4.5 4.5L19 7.5" /></Svg>;
export const Cross = (p: P) => <Svg {...p}><path d="M7 7l10 10M17 7L7 17" /></Svg>;
export const Alert = (p: P) => <Svg {...p}><path d="M12 4l9 16H3l9-16z" /><path d="M12 10v4M12 17.5v.2" /></Svg>;
export const Info = (p: P) => <Svg {...p}><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 7.8v.2" /></Svg>;
export const Camera = (p: P) => <Svg {...p}><path d="M4 8h3l2-2.5h6L17 8h3v11H4z" /><circle cx="12" cy="13" r="3.5" /></Svg>;
export const Upload = (p: P) => <Svg {...p}><path d="M12 16V4M7 9l5-5 5 5M4 16v4h16v-4" /></Svg>;
export const Clock = (p: P) => <Svg {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></Svg>;
export const Phone = (p: P) => <Svg {...p}><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a1 1 0 0 1-1 1A16 16 0 0 1 4 5a1 1 0 0 1 1-1z" /></Svg>;
export const Car = (p: P) => <Svg {...p}><path d="M3 16v-3l2-5h14l2 5v3H3z" /><circle cx="7" cy="16.5" r="1.8" /><circle cx="17" cy="16.5" r="1.8" /><path d="M5 12h14" /></Svg>;
export const Wallet = (p: P) => <Svg {...p}><path d="M4 7h14a2 2 0 0 1 2 2v9a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7z" /><path d="M4 7l11-3 1 3M16 13h2" /></Svg>;
export const Trend = (p: P) => <Svg {...p}><path d="M4 17l6-6 4 4 6-7" /><path d="M15 8h5v5" /></Svg>;
export const User = (p: P) => <Svg {...p}><circle cx="12" cy="8" r="3.5" /><path d="M5 20c.6-4 3.4-6 7-6s6.4 2 7 6" /></Svg>;
export const MapPin = (p: P) => <Svg {...p}><path d="M12 21s-6.5-6.1-6.5-11a6.5 6.5 0 0 1 13 0c0 4.9-6.5 11-6.5 11z" /><circle cx="12" cy="10" r="2.3" /></Svg>;
export const Trash = (p: P) => <Svg {...p}><path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13" /></Svg>;
export const Building = (p: P) => <Svg {...p}><path d="M4 20V6l8-3 8 3v14M4 20h16M9 20v-5h6v5M8 9h1M12 9h1M16 9h1" /></Svg>;

export const CASE_ICON: Record<string, (p: P) => JSX.Element> = {
  police: Doc, driver: Wheel, glass: Glass, theft: Key, passengers: Users, fire: Flame, nature: Storm,
  assistance: Tow, defense: Scale,
};
