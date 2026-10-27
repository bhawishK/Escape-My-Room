/** A shared-state revision is shown only when the page has not already seen a newer one. */
export function showsRevision(current: number | null, next: number): boolean {
  return current === null || next >= current;
}
