import dayjs from "dayjs";
import customParseFormat from "dayjs/plugin/customParseFormat";
import isSameOrAfter from "dayjs/plugin/isSameOrAfter";
import isSameOrBefore from "dayjs/plugin/isSameOrBefore";
import isoWeek from "dayjs/plugin/isoWeek";

/**
 * Single, boot-time extension of every dayjs plugin the app relies on.
 *
 * This module is imported **first** in ``main.tsx`` (and in the vitest
 * setup) so the plugins live on the dayjs singleton before any component
 * renders. Previously each of ~60 modules called ``dayjs.extend(...)`` as
 * its own load-time side effect, which made plugin availability depend on
 * *which chunk happened to load first*. In a production build a lazily
 * loaded route chunk could mount a widget that needs ``isoWeek`` /
 * ``customParseFormat`` before any of those modules had run — the exact
 * cause of the intermittent AntD ``DatePicker`` crash ("can't access
 * property 'date'") on the configuration ``valid_from`` field.
 *
 * Keep this list a **superset** of every plugin used anywhere in ``src`` —
 * dropping one here silently breaks the feature that relied on it.
 */
export const DAYJS_PLUGINS = [
  customParseFormat,
  isSameOrAfter,
  isSameOrBefore,
  isoWeek,
] as const;

for (const plugin of DAYJS_PLUGINS) {
  dayjs.extend(plugin);
}
