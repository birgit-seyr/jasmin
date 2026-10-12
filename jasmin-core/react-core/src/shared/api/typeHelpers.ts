/**
 * Type helpers for building payloads against the orval-generated models.
 *
 * Orval marks server-generated fields `readonly` and types every generated
 * create/update function over its module-PRIVATE `NonReadonly<T>` mapped type
 * — which is why `payload as unknown as Model` casts grew at call sites.
 * `Writable<T>` is the exported equivalent: annotate the payload literal with
 * it and field names / value types stay compiler-checked. A PATCH body needs
 * none of this: its generated `Patched…` type is all-optional already.
 *
 *   const payload: Writable<OrderContent> = { reseller, offer, amount };
 *   await commissioningOrderContentsCreate(payload);
 *
 *   const patch: PatchedShareDelivery = { joker_taken };
 *   await commissioningShareDeliveryPartialUpdate(id, patch);
 */
export type Writable<T> = { -readonly [K in keyof T]: T[K] };
