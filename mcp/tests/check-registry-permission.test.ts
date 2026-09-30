import { describe, expect, it } from 'vitest';
import {
  isResourceMatch,
  checkPermission,
} from '../scripts/check-registry-permission.mjs';

// Covers the release preflight added to close CRITICAL 1: the Registry
// grants permission on the raw, case-sensitive OIDC repository_owner claim
// (io.github.<owner>/*), and isResourceMatch here must reproduce upstream's
// internal/auth/jwt.go exactly -- a prefix match with no normalization -- so
// this check catches a namespace-case mismatch before npm publish runs
// rather than after.

describe('isResourceMatch (mirrors upstream internal/auth/jwt.go)', () => {
  it('matches a wildcard prefix pattern', () => {
    expect(isResourceMatch('io.github.kinnister/agentic-os', 'io.github.kinnister/*')).toBe(true);
  });

  it('is case-sensitive: capitalized grant does not cover the lowercase login', () => {
    expect(isResourceMatch('io.github.kinnister/agentic-os', 'io.github.Kinnister/*')).toBe(false);
  });

  it('is case-sensitive the other way too', () => {
    expect(isResourceMatch('io.github.Kinnister/agentic-os', 'io.github.kinnister/*')).toBe(false);
  });

  it('matches an exact (non-wildcard) pattern only exactly', () => {
    expect(isResourceMatch('io.github.kinnister/agentic-os', 'io.github.kinnister/agentic-os')).toBe(true);
    expect(isResourceMatch('io.github.kinnister/agentic-os-2', 'io.github.kinnister/agentic-os')).toBe(false);
  });

  it('does not match an unrelated namespace', () => {
    expect(isResourceMatch('io.github.kinnister/agentic-os', 'io.github.someoneelse/*')).toBe(false);
  });
});

describe('checkPermission', () => {
  it('finds a covering publish permission', () => {
    const matches = checkPermission('io.github.kinnister/agentic-os', [
      { action: 'publish', resource: 'io.github.kinnister/*' },
    ]);
    expect(matches).toHaveLength(1);
  });

  it('returns empty when the only grant is a case mismatch (the CRITICAL 1 bug)', () => {
    const matches = checkPermission('io.github.kinnister/agentic-os', [
      { action: 'publish', resource: 'io.github.Kinnister/*' },
    ]);
    expect(matches).toEqual([]);
  });

  it('ignores permissions for a different action (e.g. edit)', () => {
    const matches = checkPermission('io.github.kinnister/agentic-os', [
      { action: 'edit', resource: 'io.github.kinnister/*' },
    ]);
    expect(matches).toEqual([]);
  });

  it('returns empty for an empty permissions array', () => {
    expect(checkPermission('io.github.kinnister/agentic-os', [])).toEqual([]);
  });

  it('ignores malformed permission entries instead of throwing', () => {
    const matches = checkPermission('io.github.kinnister/agentic-os', [
      null,
      { action: 'publish' }, // no resource field
      { action: 'publish', resource: 'io.github.kinnister/*' },
    ] as unknown as Array<{ action: string; resource: string }>);
    expect(matches).toHaveLength(1);
  });
});
