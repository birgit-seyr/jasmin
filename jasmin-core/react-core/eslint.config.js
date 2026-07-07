import js from '@eslint/js'
import globals from 'globals'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

const browserWithProcess = {
  ...globals.browser,
  // Vite injects `process.env.NODE_ENV` at build time via the `define` option,
  // so it's a legitimate global in src/ files even though we don't run in Node.
  process: 'readonly',
}

// i18n: no inline fallbacks. The German locale files are the source of truth
// and `de` is the `fallbackLng`, so `t("ns.key", "Some text")` only duplicates
// copy that then rots independently of the locale JSON. Forbid a string / template
// literal as the 2nd argument to `t(...)` (both bare `t` and `i18n.t`); an
// options object `t("ns.key", { count })` is fine and not matched here.
// esquery's `:nth-child` counts only the CallExpression's `arguments` (the
// callee is excluded), so the 2nd argument is `:nth-child(2)`.
const noInlineI18nFallback = [
  {
    selector:
      "CallExpression[callee.name='t'] > Literal:nth-child(2), CallExpression[callee.property.name='t'] > Literal:nth-child(2)",
    message:
      'i18n: no inline fallback. Use bare t("ns.key") and add the key to src/shared/i18n/locales/de/*.json (de is the source of truth + fallbackLng).',
  },
  {
    selector:
      "CallExpression[callee.name='t'] > TemplateLiteral:nth-child(2), CallExpression[callee.property.name='t'] > TemplateLiteral:nth-child(2)",
    message:
      'i18n: no inline fallback. Use bare t("ns.key") and add the key to src/shared/i18n/locales/de/*.json (de is the source of truth + fallbackLng).',
  },
]

export default [
  {
    ignores: [
      'dist',
      'src/shared/api/generated',
      'src/features/cultivation/pages',
      'src/features/economics/pages',
      'src/features/staff/pages',
      'src/pages/gdpr',
    ],
  },
  // Node-side config files (vite.config*.js, this file, postcss/tailwind configs)
  {
    files: ['*.config.js', 'vite.config.*.js', 'eslint.config.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...globals.node, ...globals.browser },
    },
    rules: {
      ...js.configs.recommended.rules,
      // Proxy/onProxyReq callbacks are called with (proxy, options, req, res),
      // even when our handler only uses one or two of them.
      'no-unused-vars': [
        'error',
        { args: 'none', varsIgnorePattern: '^[A-Z_]' },
      ],
    },
  },
  {
    files: ['**/*.{js,jsx}'],
    ignores: ['*.config.js', 'vite.config.*.js', 'eslint.config.js'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: browserWithProcess,
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...js.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      'no-unused-vars': ['error', { varsIgnorePattern: '^[A-Z_]' }],
      'react-refresh/only-export-components': 'off',
      // Bare `console.log` / `info` / `debug` is forbidden (debug leftovers
      // mustn't ship). `warn` / `error` are allowed; for intentional dev
      // logging use the `logger` util in src/shared/utils/logger.ts.
      'no-console': ['error', { allow: ['warn', 'error'] }],
      'no-restricted-syntax': ['error', ...noInlineI18nFallback],
    },
  },
  ...tseslint.configs.recommended.map((config) => ({
    ...config,
    files: ['**/*.{ts,tsx}'],
  })),
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      globals: browserWithProcess,
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': 'off',
      // The codebase intentionally uses untyped record shapes for table rows
      // and DRF-generated payloads — flag the most useful checks, mute the noise.
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { varsIgnorePattern: '^[A-Z_]', argsIgnorePattern: '^_' },
      ],
      // See the js/jsx block: forbid bare console.log/info/debug; route
      // intentional dev logging through the `logger` util.
      'no-console': ['error', { allow: ['warn', 'error'] }],
      'no-restricted-syntax': ['error', ...noInlineI18nFallback],
    },
  },
  // Accessibility (jsx-a11y): static, build-time catch of the machine-detectable
  // a11y issues in hand-written JSX — missing alt, label-less controls, bad ARIA,
  // handlers on non-interactive elements, etc. Rules-only (the plugin's own
  // languageOptions are NOT spread) so the TS parser + parserOptions set by the
  // blocks above stay intact; jsx parsing is already enabled there. NOTE: this
  // lints RAW JSX only — it can't see inside AntD components, so runtime DOM
  // issues from the component library need the axe-in-Vitest layer (src/test).
  {
    files: ['**/*.{jsx,tsx}'],
    ignores: [
      '**/__tests__/**',
      '**/*.test.{ts,tsx}',
      // Super-admin / platform UI is an internal tenant-management tool, not
      // member-facing — a11y conformance is out of scope there. Re-include by
      // deleting these globs if that ever changes.
      'src/features/platform/**',
      'src/app/SuperAdminApp.tsx',
    ],
    plugins: { 'jsx-a11y': jsxA11y },
    rules: {
      // Every recommended rule is 'error' — a rule with ZERO debt genuinely
      // gates new code (an <img> with no alt, a label-less control, an autoFocus
      // outside the allow-listed forms below, etc. fail CI immediately). All
      // jsx-a11y debt is now cleared, so nothing is downgraded here.
      ...jsxA11y.flatConfigs.recommended.rules,
    },
  },
  // no-autofocus is 'error' globally (above), but autofocusing the PRIMARY input
  // of a single-purpose form is the intended, WCAG-defensible UX — so turn it
  // OFF for exactly those focused-task contexts (auth / re-auth / 2FA + the note
  // editor). This is cleaner than mid-attribute inline disables and still gates
  // any new, unjustified autoFocus everywhere else.
  {
    files: [
      'src/features/auth/pages/**/*.{jsx,tsx}',
      'src/shared/auth/**/*.{jsx,tsx}',
      'src/shared/profile/TwoFactorPanel.tsx',
      'src/features/commissioning/components/OrderInfoPanel.tsx',
    ],
    rules: {
      'jsx-a11y/no-autofocus': 'off',
    },
  },
  // The logger façade wraps `console.*`, and test files print diagnostics —
  // both may use bare console freely. Placed last so it overrides the
  // no-console rules above for these files.
  {
    files: [
      'src/shared/utils/logger.ts',
      '**/__tests__/**',
      '**/*.test.{ts,tsx}',
      'src/test/**',
    ],
    rules: {
      'no-console': 'off',
    },
  },
  // Layer boundary: ``shared/`` is the bottom layer — it must not reach UP
  // into feature or app code. Keeps the dependency graph one-way
  // (features/app -> shared, never the reverse) so the shared layer stays
  // extractable/publishable. See docs/frontend-structure-proposal.md.
  // (The commissioning bounded-context one-way rule is enforced in the next
  // block, using plain no-restricted-imports — no extra plugin needed.)
  {
    files: ['src/shared/**/*.{ts,tsx}'],
    ignores: ['**/__tests__/**', '**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@features/*', '@features/**', '@app/*', '@app/**'],
              message:
                'shared/ must not import from features/ or app/. Move the shared-but-feature-typed code into the owning feature, or lift the shared part down into shared/.',
            },
          ],
        },
      ],
    },
  },
  // Commissioning bounded context (commissioning + members + abos + customer +
  // warehouse) must stay one-way extractable: it may import shared/ and other
  // context features, but NOT non-context features. Mirrors the backend rule
  // for apps/commissioning/. Other (non-context) features MAY import FROM the
  // context — that direction is fine.
  {
    files: [
      'src/features/commissioning/**/*.{ts,tsx,js,jsx}',
      'src/features/members/**/*.{ts,tsx,js,jsx}',
      'src/features/abos/**/*.{ts,tsx,js,jsx}',
      'src/features/customer/**/*.{ts,tsx,js,jsx}',
      'src/features/warehouse/**/*.{ts,tsx,js,jsx}',
    ],
    ignores: ['**/__tests__/**', '**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: [
                '@features/configuration',
                '@features/configuration/**',
                '@features/auth',
                '@features/auth/**',
                '@features/platform',
                '@features/platform/**',
                '@features/public',
                '@features/public/**',
                '@features/staff',
                '@features/staff/**',
                '@features/economics',
                '@features/economics/**',
                '@features/cultivation',
                '@features/cultivation/**',
              ],
              message:
                'The commissioning bounded context (commissioning/members/abos/customer/warehouse) must not import non-context features — it has to stay one-way extractable. Lift the shared part into shared/, or invert the dependency.',
            },
          ],
        },
      ],
    },
  },
]
