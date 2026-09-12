'use client';

import { useSyncExternalStore, type MouseEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { IconMoon, IconSun } from '@/components/ui/Icons';
import type { Theme } from '@/lib/theme';
import { toggleThemeWithTransition } from '@/lib/themeTransition';

function subscribe(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
  });
  return () => observer.disconnect();
}

function getSnapshot(): Theme {
  return document.documentElement.dataset['theme'] === 'light' ? 'light' : 'dark';
}

/**
 * Dark/light switch.
 *
 * It reads the theme straight from the `data-theme` attribute on <html>, so it
 * stays correct when something else (the command palette) changes the theme.
 * On the server the theme is unknown, so the button renders neutral and
 * disabled until hydration rather than committing to the wrong icon.
 */
export function ThemeToggle() {
  const theme = useSyncExternalStore<Theme | null>(subscribe, getSnapshot, () => null);

  const onClick = (event: MouseEvent<HTMLButtonElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    toggleThemeWithTransition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 });
  };

  const nextLabel = theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme';

  return (
    <Button
      variant="ghost"
      size="sm"
      iconOnly
      onClick={onClick}
      aria-label={nextLabel}
      title={nextLabel}
      disabled={theme === null}
    >
      {theme === 'light' ? <IconMoon size={16} /> : <IconSun size={16} />}
    </Button>
  );
}
