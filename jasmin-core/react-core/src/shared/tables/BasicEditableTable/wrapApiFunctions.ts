import type { ApiFunctions, TableRecord } from "./types";

/**
 * Raw, un-adapted endpoint functions — the shape an Orval-generated client
 * hands you. Generic over the ROW type (`TRow`) and the list-params type
 * (`TListParams`): `create`/`update` take the typed row so call sites can pass
 * the Orval functions directly (no `as unknown as Foo` cast), `list` takes the
 * typed `*ListParams`, and `delete` resolves to whatever the destroy endpoint
 * returns. Inputs are typed here (call-site facing); the loose form-value
 * inputs live on {@link ApiFunctions} (table facing).
 */
export interface RawApiFunctions<
  TRow extends TableRecord = TableRecord,
  TListParams extends Record<string, unknown> = Record<string, string>,
> {
  list?: (params?: TListParams) => Promise<unknown>;
  create?: (data: TRow) => Promise<unknown>;
  update?: (id: string, data: TRow) => Promise<unknown>;
  delete?: (id: string, data?: Record<string, unknown>) => Promise<unknown>;
}

/**
 * Adapt raw endpoint functions to the {@link ApiFunctions} shape EditableTable
 * consumes — wrapping `list`/`create`/`update` results in the `{ data }`
 * envelope the table expects and passing `delete` through untouched. The
 * loose→typed bridging casts live HERE (one place) so call sites stay clean.
 *
 * Untyped (back-compat): call sites keep their own param/payload casts.
 * ```ts
 * const apiFunctions = useMemo<ApiFunctions>(
 *   () =>
 *     wrapApiFunctions({
 *       create: (payload) => fooCreate(payload as unknown as Foo),
 *       update: (id, payload) => fooPartialUpdate(id, payload as unknown as Foo),
 *       delete: (id) => fooDestroy(id),
 *     }),
 *   [],
 * );
 * ```
 *
 * Typed: instantiate over `Foo & TableRecord` and the casts vanish — the row
 * type is an intersection so it's assignable to the Orval request type.
 * (`ApiFunctions` itself is non-generic; the row typing lives on
 * `wrapApiFunctions<FooRow>`.)
 * ```ts
 * type FooRow = Foo & TableRecord;
 * const apiFunctions = useMemo<ApiFunctions>(
 *   () =>
 *     wrapApiFunctions<FooRow>({
 *       create: (payload) => fooCreate(payload),
 *       update: (id, payload) => fooPartialUpdate(id, payload),
 *       delete: (id) => fooDestroy(id),
 *     }),
 *   [],
 * );
 * ```
 */
export function wrapApiFunctions<
  TRow extends TableRecord = TableRecord,
  TListParams extends Record<string, unknown> = Record<string, string>,
>(fns: RawApiFunctions<TRow, TListParams>): ApiFunctions {
  const wrapped: ApiFunctions = {};
  const { list, create, update, delete: destroy } = fns;
  if (list)
    wrapped.list = (params) =>
      list(params as TListParams).then((data) => ({ data }));
  if (create)
    wrapped.create = (data) => create(data as TRow).then((res) => ({ data: res }));
  if (update)
    wrapped.update = (id, data) =>
      update(id, data as TRow).then((res) => ({ data: res }));
  if (destroy) wrapped.delete = destroy;
  return wrapped;
}
