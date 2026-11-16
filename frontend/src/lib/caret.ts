/**
 * Caret bookkeeping for inputs that reformat on every keystroke.
 * Positions are tracked by "significant character" index (digits and the
 * decimal mark), never by string offset, because regrouping shifts offsets.
 */

const SIGNIFICANT = /[\d۰-۹٠-٩.٫/]/;

export function digitsBefore(text: string, offset: number): number {
  let count = 0;
  for (let i = 0; i < Math.min(offset, text.length); i++) {
    if (SIGNIFICANT.test(text[i])) count++;
  }
  return count;
}

export function caretAfterDigits(text: string, digits: number): number {
  if (digits <= 0) return 0;
  let count = 0;
  for (let i = 0; i < text.length; i++) {
    if (SIGNIFICANT.test(text[i]) && ++count === digits) return i + 1;
  }
  return text.length;
}
