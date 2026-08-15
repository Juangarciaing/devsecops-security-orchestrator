import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// Structural test over the raw stylesheet: index.css is not imported by any
// component under test (jsdom does not execute @import/@theme), so the only
// way to pin its additive token contract is to read the file as text and
// assert the exact lines/substrings this PR must add. This also protects
// Req1 — every pre-existing OKLCH color line must stay byte-identical.

const thisDir = dirname(fileURLToPath(import.meta.url))
const cssPath = join(thisDir, 'index.css')
const css = readFileSync(cssPath, 'utf-8')

describe('index.css token layer (PR1)', () => {
  it('keeps every pre-existing OKLCH color token line byte-identical', () => {
    const existingColorLines = [
      '--background: oklch(0.16 0.02 250);',
      '--foreground: oklch(0.96 0.01 250);',
      '--card: oklch(0.2 0.025 250);',
      '--card-foreground: oklch(0.96 0.01 250);',
      '--popover: oklch(0.2 0.025 250);',
      '--popover-foreground: oklch(0.96 0.01 250);',
      '--primary: oklch(0.72 0.1 195);',
      '--primary-foreground: oklch(0.14 0.02 195);',
      '--secondary: oklch(0.28 0.03 250);',
      '--secondary-foreground: oklch(0.96 0.01 250);',
      '--muted: oklch(0.24 0.02 250);',
      '--muted-foreground: oklch(0.68 0.02 250);',
      '--accent: oklch(0.3 0.03 250);',
      '--accent-foreground: oklch(0.96 0.01 250);',
      '--destructive: oklch(0.55 0.19 25);',
      '--destructive-foreground: oklch(0.98 0.005 25);',
      '--border: oklch(1 0 0 / 10%);',
      '--input: oklch(1 0 0 / 15%);',
      '--ring: oklch(0.72 0.1 195 / 55%);',
      '--severity-critical: oklch(0.55 0.19 25);',
      '--severity-critical-foreground: oklch(0.98 0.005 25);',
      '--severity-high: oklch(0.68 0.14 55);',
      '--severity-high-foreground: oklch(0.16 0.03 55);',
      '--severity-medium: oklch(0.78 0.13 95);',
      '--severity-medium-foreground: oklch(0.16 0.03 95);',
      '--severity-low: oklch(0.5 0.1 235);',
      '--severity-low-foreground: oklch(0.98 0.005 235);',
      '--severity-info: oklch(0.53 0.12 300);',
      '--severity-info-foreground: oklch(0.98 0.005 300);',
      '--status-pending: oklch(0.75 0.03 250);',
      '--status-running: oklch(0.68 0.1 195);',
      '--status-completed: oklch(0.72 0.14 145);',
      '--status-failed: oklch(0.66 0.18 25);',
      '--status-cancelled: oklch(0.65 0.02 250);',
      '--sidebar: oklch(0.18 0.02 250);',
      '--sidebar-foreground: oklch(0.96 0.01 250);',
      '--sidebar-primary: oklch(0.72 0.1 195);',
      '--sidebar-primary-foreground: oklch(0.14 0.02 195);',
      '--sidebar-accent: oklch(0.26 0.025 250);',
      '--sidebar-accent-foreground: oklch(0.96 0.01 250);',
      '--sidebar-border: oklch(1 0 0 / 10%);',
      '--sidebar-ring: oklch(0.72 0.1 195 / 55%);',
    ]

    for (const line of existingColorLines) {
      expect(css).toContain(line)
    }
  })

  it('imports exactly the 5 required @fontsource latin, non-italic weight files', () => {
    const requiredImports = [
      "@fontsource/ibm-plex-sans/latin-400.css",
      "@fontsource/ibm-plex-sans/latin-500.css",
      "@fontsource/ibm-plex-sans/latin-600.css",
      "@fontsource/ibm-plex-mono/latin-400.css",
      "@fontsource/ibm-plex-mono/latin-500.css",
    ]

    for (const spec of requiredImports) {
      expect(css).toContain(`@import '${spec}';`)
    }

    expect(css).not.toContain('ibm-plex-sans/latin-700')
    expect(css).not.toContain('italic')
  })

  it('defines the 7 semantic type-scale steps with line-height/letter-spacing/font-weight modifiers', () => {
    const steps = [
      'display',
      'heading',
      'subheading',
      'body',
      'label',
      'meta',
      'code',
    ]

    for (const step of steps) {
      expect(css).toContain(`--text-${step}:`)
      expect(css).toContain(`--text-${step}--line-height:`)
      expect(css).toContain(`--text-${step}--letter-spacing:`)
      expect(css).toContain(`--text-${step}--font-weight:`)
    }
  })

  it('defines motion duration/easing raws, aliases, keyframes, and a global reduced-motion gate', () => {
    expect(css).toContain('--duration-fast:')
    expect(css).toContain('--duration-normal:')
    expect(css).toContain('--duration-slow:')
    expect(css).toContain('--easing-standard:')
    expect(css).toContain('--easing-exit:')
    expect(css).toContain('--ease-standard: var(--easing-standard);')
    expect(css).toContain('--ease-exit: var(--easing-exit);')
    expect(css).toContain('--animate-row-in:')
    expect(css).toContain('--animate-status-pulse:')
    expect(css).toContain('@keyframes row-in')
    expect(css).toContain('@keyframes status-pulse')

    expect(css).toContain('prefers-reduced-motion: reduce')
    expect(css).toContain('animation-duration: .01ms !important')
    expect(css).toContain('transition-duration: .01ms !important')
  })

  it('defines elevation surface and shadow tokens', () => {
    expect(css).toContain('--surface-raised:')
    expect(css).toContain('--surface-sunken:')
    expect(css).toContain('--elevation-1:')
    expect(css).toContain('--elevation-2:')
    expect(css).toContain('--elevation-3:')
    expect(css).toContain('--color-surface-raised: var(--surface-raised);')
    expect(css).toContain('--color-surface-sunken: var(--surface-sunken);')
    expect(css).toContain('--shadow-e1: var(--elevation-1);')
    expect(css).toContain('--shadow-e2: var(--elevation-2);')
    expect(css).toContain('--shadow-e3: var(--elevation-3);')
  })
})
