"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { AlertTriangle, Check, Info, X } from "./Icons";

type ToastVariant = "success" | "warning" | "danger" | "info";

type ToastInput = {
  variant?: ToastVariant;
  title: string;
  description?: string;
  /** Auto-dismiss after this many ms. Pass 0 to keep until dismissed. */
  duration?: number;
};

type ToastItem = {
  id: string;
  variant: ToastVariant;
  title: string;
  description?: string;
};

type ToastContextValue = { toast: (input: ToastInput) => void };

const ToastContext = createContext<ToastContextValue | null>(null);

const ICON = {
  success: Check,
  warning: AlertTriangle,
  danger: AlertTriangle,
  info: Info,
} as const;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: string) => {
    setItems((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const toast = useCallback(
    ({ variant = "info", title, description, duration = 5000 }: ToastInput) => {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      setItems((prev) => [...prev, { id, variant, title, description }]);
      if (duration > 0) {
        window.setTimeout(() => dismiss(id), duration);
      }
    },
    [dismiss],
  );

  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {items.length > 0 ? (
        <div className="toastViewport" role="region" aria-label="Varsler">
          {items.map((item) => {
            const Icon = ICON[item.variant];
            return (
              <div
                key={item.id}
                className={`toast toast--${item.variant}`}
                role={item.variant === "danger" ? "alert" : "status"}
                aria-live={item.variant === "danger" ? "assertive" : "polite"}
              >
                <Icon size={18} aria-hidden="true" />
                <div className="toastBody">
                  <span className="toastTitle">{item.title}</span>
                  {item.description ? (
                    <span className="toastText">{item.description}</span>
                  ) : null}
                </div>
                <button
                  type="button"
                  className="toastClose"
                  onClick={() => dismiss(item.id)}
                  aria-label="Lukk varsel"
                >
                  <X size={16} aria-hidden="true" />
                </button>
              </div>
            );
          })}
        </div>
      ) : null}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within a <ToastProvider>");
  }
  return ctx;
}
