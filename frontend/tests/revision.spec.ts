import { expect, test } from '@playwright/test';
import { showsRevision } from '../src/revision';

test('an older room revision does not replace the one already shown', () => {
  expect(showsRevision(null, 1)).toBe(true);
  expect(showsRevision(4, 5)).toBe(true);
  expect(showsRevision(4, 4)).toBe(true);
  expect(showsRevision(4, 3)).toBe(false);
});
