// Lightweight, dependency-free i18n.
//
// Hand-rolled instead of react-i18next to keep runtime deps minimal. Dictionaries are flat `Record<string,string>` keyed by "<area>.<purpose>"
// dot paths (e.g. "login.title"). tr.ts and en.ts MUST share the same key set; a
// missing key falls back to Turkish, then to the raw key so nothing renders blank.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { tr } from "./locales/tr";
import { en } from "./locales/en";

export type Lang = "tr" | "en";

const DICTS: Record<Lang, Record<string, string>> = { tr, en };
const STORAGE_KEY = "ui.lang";

/** Pick the initial language: saved choice → browser hint → Turkish default. */
function detectInitial(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "tr" || saved === "en") return saved;
    if ((navigator.language || "").toLowerCase().startsWith("en")) return "en";
  } catch {
    // localStorage/navigator can be unavailable (SSR, sandboxed) — fall through.
  }
  return "tr";
}

type TranslateFn = (key: string, vars?: Record<string, string | number>) => string;

interface LanguageContextValue {
  lang: Lang;
  setLang: (l: Lang) => void;
  /** Look up a key in the active language. `vars` replaces `{name}` placeholders. */
  t: TranslateFn;
}

const LanguageContext = createContext<LanguageContextValue | null>(null);

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>(detectInitial);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch {
      // ignore write failures (private mode, etc.)
    }
    document.documentElement.lang = lang;
    // Keep the browser tab title in sync with the brand name for the active
    // language (looked up via DICTS since `t` is defined below this effect).
    document.title = DICTS[lang]["brand.name"] ?? DICTS.tr["brand.name"] ?? "3D Studio";
  }, [lang]);

  const t = useCallback<TranslateFn>(
    (key, vars) => {
      let s = DICTS[lang][key] ?? DICTS.tr[key] ?? key;
      if (vars) {
        for (const [k, v] of Object.entries(vars)) {
          s = s.replace(new RegExp(`\\{${k}\\}`, "g"), String(v));
        }
      }
      return s;
    },
    [lang],
  );

  return (
    <LanguageContext.Provider value={{ lang, setLang, t }}>
      {children}
      <LanguageToggle />
    </LanguageContext.Provider>
  );
}

/** Access the active language and the `t()` translator. */
export function useT(): LanguageContextValue {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error("useT must be used within a LanguageProvider");
  return ctx;
}

/**
 * Fixed TR/EN switch, rendered once by the provider so it appears on every page
 * without touching each page's header. Bottom-left keeps it clear of the top
 * toolbars and the 3D designer's right-hand controls.
 */
export function LanguageToggle() {
  const { lang, setLang } = useT();
  const langs: Lang[] = ["tr", "en"];
  return (
    <div className="fixed bottom-3 left-3 z-50 inline-flex overflow-hidden rounded-md border border-zinc-700 text-xs shadow-lg">
      {langs.map((l) => (
        <button
          key={l}
          type="button"
          onClick={() => setLang(l)}
          aria-pressed={lang === l}
          className={
            "px-2.5 py-1 font-medium transition-colors " +
            (lang === l
              ? "bg-zinc-200 text-zinc-900"
              : "bg-zinc-800/90 text-zinc-300 hover:bg-zinc-700")
          }
        >
          {l.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
