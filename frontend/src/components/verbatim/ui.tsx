import type { ReactNode } from 'react';
import { clsx } from '@/utils/verbatimFormat';

export function Card({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={clsx(
        'rounded-lg border border-slate-800 bg-slate-900/60 p-4',
        className,
      )}
    >
      {children}
    </div>
  );
}

export function Badge({
  children,
  color = 'slate',
  className,
}: {
  children: ReactNode;
  color?: 'slate' | 'green' | 'red' | 'yellow' | 'blue' | 'purple';
  className?: string;
}) {
  const colors: Record<string, string> = {
    slate: 'bg-slate-700 text-slate-200',
    green: 'bg-green-900 text-green-300 border border-green-700',
    red: 'bg-red-900 text-red-300 border border-red-700',
    yellow: 'bg-yellow-900 text-yellow-300 border border-yellow-700',
    blue: 'bg-blue-900 text-blue-300 border border-blue-700',
    purple: 'bg-purple-900 text-purple-300 border border-purple-700',
  };
  return (
    <span
      className={clsx(
        'inline-block rounded px-1.5 py-0.5 text-xs font-medium',
        colors[color],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-slate-400">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-600 border-t-slate-300" />
      {label && <span className="text-sm">{label}</span>}
    </div>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="rounded border border-red-800 bg-red-950/60 p-3 text-sm text-red-300">
      {message}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded border border-dashed border-slate-700 p-6 text-center text-sm text-slate-500">
      {children}
    </div>
  );
}
