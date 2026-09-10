/**
 * Save a Blob to the analyst's machine.
 *
 * Everything here is same-origin and short-lived: the object URL is revoked on
 * the next tick, and no third party is ever contacted (AD-5). Guarded for the
 * server render, where `document` does not exist.
 */
export function downloadBlob(blob: Blob, filename: string): void {
  if (typeof document === 'undefined' || typeof URL.createObjectURL !== 'function') return;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Revoking synchronously can cancel the download in some browsers.
  setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

export function downloadText(text: string, filename: string, mediaType: string): void {
  downloadBlob(new Blob([text], { type: `${mediaType};charset=utf-8` }), filename);
}
