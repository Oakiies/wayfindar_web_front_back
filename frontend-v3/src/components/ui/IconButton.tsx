import React from 'react';

type Tone = 'light' | 'dark' | 'solid';

interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** `light` floats over the map, `dark` over the camera feed, `solid` is the primary ink circle. */
  tone?: Tone;
  label: string;
  children: React.ReactNode;
}

const TONE_CLASS: Record<Tone, string> = {
  light: 'glass text-ink-2 hover:text-ink',
  dark: 'glass-dark text-white hover:bg-white/20',
  solid: 'bg-ink text-white shadow-[var(--shadow-card)]',
};

/**
 * The single circular control used across every view. Previously each view
 * hand-rolled its own 38px circle with slightly different inline styles.
 */
const IconButton: React.FC<IconButtonProps> = ({
  tone = 'light',
  label,
  children,
  className = '',
  ...rest
}) => (
  <button
    type="button"
    aria-label={label}
    title={label}
    className={`press flex h-11 w-11 shrink-0 items-center justify-center rounded-full ${TONE_CLASS[tone]} ${className}`}
    {...rest}
  >
    {children}
  </button>
);

export default IconButton;
