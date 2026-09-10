'use client';

import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from 'react';
import { cx } from '@/lib/cx';
import styles from './ui.module.css';

export interface SliderProps extends Omit<
  InputHTMLAttributes<HTMLInputElement>,
  'type' | 'id' | 'value'
> {
  label: ReactNode;
  value: number;
  min: number;
  max: number;
  step?: number;
  /** Shown instead of the raw number, e.g. `2026-08-13 10:42Z` or `60%`. */
  valueText?: string;
  labelHidden?: boolean;
  containerClassName?: string;
}

/**
 * A native `<input type="range">`.
 *
 * Native on purpose: it already handles Left/Right, Home/End, Page Up/Down and
 * touch drag on every platform, and `aria-valuetext` lets a screen reader read
 * "2026-08-13 10:42 UTC" instead of "1755081720". A custom slider would have to
 * re-earn all of that.
 */
export const Slider = forwardRef<HTMLInputElement, SliderProps>(function Slider(
  {
    label,
    value,
    min,
    max,
    step = 1,
    valueText,
    labelHidden = false,
    className,
    containerClassName,
    disabled,
    ...rest
  },
  ref,
) {
  const id = useId();
  return (
    <div className={cx(styles.sliderRow, containerClassName)}>
      <label htmlFor={id} className={cx(styles.sliderLabel, labelHidden && 'sr-only')}>
        {label}
      </label>
      <input
        {...rest}
        ref={ref}
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        aria-valuetext={valueText}
        className={cx(styles.slider, className)}
      />
      {valueText ? (
        <output htmlFor={id} className={styles.sliderValue}>
          {valueText}
        </output>
      ) : null}
    </div>
  );
});
