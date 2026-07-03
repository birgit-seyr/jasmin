/**
 * Type helpers for building payloads against the orval-generated models.
 *
 * Orval marks server-generated fields `readonly` and types every generated
 * create/update function over its module-PRIVATE `NonReadonly<T>` mapped type
 * — which is why `payload as unknown as Model` casts grew at call sites.
 * `Writable<T>` is the exported equivalent: annotate the payload literal with
 * it and field names / value types stay compiler-checked, leaving at most one
 * documented directional cast at the call (for PATCH partials against a
 * full-model signature).
 *
 *   const payload: Writable<OrderContent> = { reseller, offer, amount };
 *   await commissioningOrderContentsCreate(payload);
 *
 *   const patch: Partial<Writable<ShareDelivery>> = { joker_taken };
 *   await commissioningShareDeliveryPartialUpdate(id, patch as ShareDelivery);
 */
export type Writable<T> = { -readonly [K in keyof T]: T[K] };
