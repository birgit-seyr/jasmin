#!/usr/bin/env node
// Ratchet check for the per-file pins in eslint.hygiene-pins.js.
//
// `npm run lint` enforces a pin as a CEILING: a pinned file cannot get worse.
// It cannot tell whether the pin is still the file's real worst value, because
// ESLint only reports what exceeds the configured number. So a file that
// improves keeps its old pin and is free to grow straight back to it — the
// register turns into a permission list. This closes that direction: it
// re-measures every pinned file with the rule floored, and fails when a pin is
// higher than what the file now reports.
//
// Pins are keyed by path, so a renamed file silently loses its pin and is then
// judged by the global threshold. A pin pointing at a missing file is reported
// as such rather than as a measurement of zero.
//
//     node scripts/check-hygiene-pins.mjs

import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { ESLint } from 'eslint'

import {
  complexityPins,
  functionLengthPins,
  fileLengthPins,
} from '../eslint.hygiene-pins.js'

const cwd = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

// Floor every rule so ESLint reports each file's real value instead of only the
// excess over its pin. CLI/overrideConfig rules are applied last, which is what
// lets this see past both the global thresholds and the pins themselves.
const FLOOR = {
  complexity: ['error', 0],
  'max-lines-per-function': [
    'error',
    { max: 1, skipBlankLines: true, skipComments: true },
  ],
  'max-lines': ['error', { max: 1, skipBlankLines: false, skipComments: false }],
}

const RULES = [
  {
    id: 'complexity',
    pins: complexityPins,
    label: 'complexity',
    // "Arrow function has a complexity of 31. Maximum allowed is 0."
    value: (message) => Number(/complexity of (\d+)/.exec(message)?.[1]),
  },
  {
    id: 'max-lines-per-function',
    pins: functionLengthPins,
    label: 'function length',
    // "Arrow function has too many lines (433). Maximum allowed is 1."
    value: (message) => Number(/\((\d+)\)/.exec(message)?.[1]),
  },
  {
    id: 'max-lines',
    pins: fileLengthPins,
    label: 'file length',
    // "File has too many lines (1443). Maximum allowed is 1."
    value: (message) => Number(/\((\d+)\)/.exec(message)?.[1]),
  },
]

/** Worst reported value per (rule, file), keyed by repo-relative posix path. */
async function measure() {
  const eslint = new ESLint({
    cwd,
    overrideConfig: { files: ['src/**/*.{ts,tsx,js,jsx}'], rules: FLOOR },
  })
  const worst = new Map(RULES.map((rule) => [rule.id, new Map()]))
  for (const result of await eslint.lintFiles(['src'])) {
    const file = path.relative(cwd, result.filePath).split(path.sep).join('/')
    for (const message of result.messages) {
      const rule = RULES.find((candidate) => candidate.id === message.ruleId)
      if (!rule) continue
      const value = rule.value(message.message)
      if (!Number.isFinite(value)) continue
      const seen = worst.get(rule.id)
      seen.set(file, Math.max(seen.get(file) ?? 0, value))
    }
  }
  return worst
}

/** The threshold a file falls back to once its pin is deleted. */
async function globalThresholds(pinned) {
  const plain = new ESLint({ cwd })
  const unpinned = ['src/main.tsx', 'src/app/App.tsx', 'src/shared/services/api.ts'].find(
    (file) => existsSync(path.join(cwd, file)) && !pinned.has(file)
  )
  if (!unpinned) return {}
  const config = await plain.calculateConfigForFile(path.join(cwd, unpinned))
  return {
    complexity: config.rules?.complexity?.[1],
    'max-lines-per-function': config.rules?.['max-lines-per-function']?.[1]?.max,
    'max-lines': config.rules?.['max-lines']?.[1]?.max,
  }
}

async function main() {
  const measured = await measure()
  const pinnedPaths = new Set(RULES.flatMap((rule) => Object.keys(rule.pins)))
  const thresholds = await globalThresholds(pinnedPaths)

  const stale = []
  const missing = []
  let total = 0

  for (const rule of RULES) {
    const seen = measured.get(rule.id)
    for (const [file, pin] of Object.entries(rule.pins)) {
      total += 1
      if (!existsSync(path.join(cwd, file))) {
        missing.push({ rule, file })
        continue
      }
      const value = seen.get(file) ?? 0
      if (value < pin) stale.push({ rule, file, pin, value })
    }
  }

  if (missing.length) {
    console.log('Pins that name a file which is not there:\n')
    for (const { rule, file } of missing) {
      console.log(`  ${file}  (${rule.label} pin)`)
    }
    console.log(
      '\nA pin is keyed by path, so a rename or a delete drops it without a word and\n' +
        'the file goes back to the global threshold. Repath the entry to the new\n' +
        'filename, or delete it if the file is gone.'
    )
  }

  if (stale.length) {
    if (missing.length) console.log()
    console.log('Pins higher than the value the file now reports:\n')
    for (const { rule, file, pin, value } of stale) {
      const threshold = thresholds[rule.id]
      const action =
        threshold !== undefined && value <= threshold
          ? `delete the entry (now under the global ${rule.label} threshold of ${threshold})`
          : `lower ${rule.label} to ${value}`
      console.log(`  ${file}: pinned ${pin}, measured ${value} — ${action}`)
    }
    console.log(
      '\nEdit eslint.hygiene-pins.js. A pin left above the measured value is standing\n' +
        'permission for the file to grow back to it, which is what the register exists\n' +
        'to prevent.'
    )
  }

  if (missing.length || stale.length) return 1

  console.log(`hygiene pins: ${total} pin(s), each at the file's measured worst value.`)
  return 0
}

process.exitCode = await main()
