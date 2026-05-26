import { useEffect, useState } from "react";

/**
 * useState that persists to localStorage. Returns the value, setter, and a
 * reset() that clears the key. Falls back gracefully if storage is unavailable.
 */
export function useLocalStorage<T>(key: string, initialValue: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = window.localStorage.getItem(key);
      if (stored === null) return initialValue;
      return JSON.parse(stored) as T;
    } catch {
      return initialValue;
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // ignore quota / privacy mode errors
    }
  }, [key, value]);

  const reset = () => {
    try {
      window.localStorage.removeItem(key);
    } catch {
      // ignore
    }
    setValue(initialValue);
  };

  return [value, setValue, reset] as const;
}
