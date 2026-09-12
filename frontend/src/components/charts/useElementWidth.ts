'use client';

import { useEffect, useRef, useState } from 'react';

/** The rendered width of an element, kept current with a ResizeObserver. */
export function useElementWidth<T extends HTMLElement>(initial = 560) {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(initial);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const update = () => setWidth(Math.max(200, Math.round(node.getBoundingClientRect().width)));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return { ref, width };
}
