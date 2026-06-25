import { useEffect, useState } from "react";

// Portrait phones are ~360-430px wide; 640px comfortably covers them while
// leaving small tablets/desktop windows on the wide layout.
const MOBILE_QUERY = "(max-width: 640px)";

export default function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(() => window.matchMedia(MOBILE_QUERY).matches);

  useEffect(() => {
    const mql = window.matchMedia(MOBILE_QUERY);
    const onChange = () => setIsMobile(mql.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  return isMobile;
}
