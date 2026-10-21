import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useNavigationType } from "react-router-dom";

export function useDebounced<T>(value: T, ms = 350): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Back/forward through the app's own navigation history (the desktop window has no browser buttons).
 *  React Router keeps the entry's position in ``history.state.idx``; forward entries are tracked here,
 *  so after a reload "forward" is unknown and stays disabled. */
export function useHistoryNav() {
  const location = useLocation();
  const type = useNavigationType();
  const navigate = useNavigate();
  const last = useRef({ key: "", max: 0 });
  const idx: number = window.history.state?.idx ?? 0;
  if (last.current.key !== location.key) {
    // a new entry drops everything after it; going back/forward keeps them
    last.current = { key: location.key, max: type === "PUSH" ? idx : Math.max(last.current.max, idx) };
  }
  return {
    canBack: idx > 0,
    canForward: idx < last.current.max,
    back: () => navigate(-1),
    forward: () => navigate(1),
  };
}

/** Phone-sized window (below Tailwind's `md`): the sidebar becomes a bottom bar and pages drill down instead of unfolding. */
const COMPACT = "(max-width: 767px)";

export function useCompact() {
  const [compact, setCompact] = useState(() => window.matchMedia(COMPACT).matches);
  useEffect(() => {
    const mq = window.matchMedia(COMPACT);
    const on = () => setCompact(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return compact;
}
