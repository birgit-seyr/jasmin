import type { ApiFunctions, TableRecord } from "./types";

/**
 * Raw, un-adapted endpoint functions — the shape an Orval-generated client
 * hands you. Generic over the ROW type (`TRow`), the list-params type
 * (`TListParams`) and the delete-params type (`TDeleteParams`, what the
 * table's `customDelete` builds): `create`/`update` take the typed row so call
 * sites can pass the Orval functions directly (no `as unknown as Foo` cast),
 * `list` takes the typed `*ListParams`, and `delete` takes the typed
 * `*DestroyParams` and resolves to whatever the destroy endpoint returns. Inputs are typed here (call-site facing); the loose form-value
 * inputs live on {@link ApiFunctions} (table facing).
 */
export interface RawApiFunctions<
  TRow extends TableRecord = TableRecord,
  TListParams extends Record<string, unknown> = Record<string, string>,
  TDeleteParams extends Record<string, unknown> = Record<string, unknown>,
> {
  list?: (params?: TListParams) => Promise<unknown>;
  create?: (data: TRow) => Promise<unknown>;
  update?: (id: string, data: TRow) => Promise<unknown>;
  /** `data` is what the table's `customDelete` built for the row. */
  delete?: (id: string, data: TDeleteParams) => Promise<unknown>;
}

/**
 * Adapt raw endpoint functions to the {@link ApiFunctions} shape EditableTable
 * consumes — wrapping `list`/`create`/`update` results in the `{ data }`
 * envelope the table expects and passing `delete` through. The
 * loose→typed bridging casts live HERE (one place) so call sites stay clean.
 *
 * Untyped (back-compat): call sites keep their own param/payload casts.
 * ```ts
 * const apiFunctions = useMemo<ApiFunctions>(
 *   () =>
 *     wrapApiFunctions({
 *       create: (payload) => fooCreate(payload as unknown as Foo),
 *       update: (id, payload) => fooPartialUpdate(id, payload as PatchedFoo),
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
  TDeleteParams extends Record<string, unknown> = Record<string, unknown>,
>(fns: RawApiFunctions<TRow, TListParams, TDeleteParams>): ApiFunctions {
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
  if (destroy)
    wrapped.delete = (id, data) => destroy(id, data as TDeleteParams);
  return wrapped;
}
