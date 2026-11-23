import { createContext, type ReactNode, useCallback, useContext, useState } from "react";

type Tone = "ok" | "error";
interface Toast {
  id: number;
  text: string;
  tone: Tone;
}

const Ctx = createContext<(text: string, tone?: Tone) => void>(() => undefined);

/** Confirmation uses the same verb as the action ("Export CSV" -> "Exported CSV"). */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: Tone = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((all) => [...all, { id, text, tone }]);
    setTimeout(() => setToasts((all) => all.filter((t) => t.id !== id)), 5000);
  }, []);
  return (
    <Ctx.Provider value={push}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role={t.tone === "error" ? "alert" : "status"}
            className={`pointer-events-auto max-w-sm px-4 py-3 text-[15px] ${
              t.tone === "error" ? "bg-status-error text-sheet" : "bg-ink text-sheet"
            }`}
          >
            {t.text}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export const useToast = () => useContext(Ctx);
