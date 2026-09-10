'use client';

import { useCallback, useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { IconMoon, IconSun } from '@/components/ui/Icons';
import { applyTheme, readStoredTheme, storeTheme, systemTheme, type Theme } from '@/lib/theme';

/**
 * Dark/light switch.
 *
 * Renders in a deliberately neutral state until mounted: the server cannot know
 * the stored preference, so committing to an icon before hydration would produce
 * a mismatch and a visible flicker.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    setTheme(readStoredTheme() ?? systemTheme());
  }, []);

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === 'light' ? 'dark' : 'light';
      applyTheme(next);
      storeTheme(next);
      return next;
    });
  }, []);

  const nextLabel = theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme';

  return (
    <Button
      variant="ghost"
      size="sm"
      iconOnly
      onClick={toggle}
      aria-label={nextLabel}
      title={nextLabel}
      disabled={theme === null}
    >
      {theme === 'light' ? <IconMoon size={16} /> : <IconSun size={16} />}
    </Button>
  );
}
