/**
 * Minimal class-name joiner.
 *
 * Deliberately not `clsx`: this is nine lines, and every dependency added to the
 * client bundle is a dependency an auditor has to read (CON-004).
 */
export type ClassValue = string | number | false | null | undefined;

export function cx(...values: ClassValue[]): string {
  let out = '';
  for (const value of values) {
    if (!value && value !== 0) continue;
    out = out ? `${out} ${value}` : String(value);
  }
  return out;
}
