// Simple reactive state store
export function createStore(initial = {}) {
  let state = { ...initial };
  const listeners = new Set();
  return {
    get: () => state,
    set: (patch) => { state = { ...state, ...patch }; listeners.forEach((fn) => fn(state)); },
    subscribe: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
  };
}

export const appStore = createStore({
  user: null,
  tenant: null,
  role: null,
  permissions: [],
  ready: false,
  activeOperatorId: null,
  operators: [],
});

// Account type and capabilities are server truth, set when the account is
// created from the admin console. A header button used to flip customer_type in
// this store, which showed a logistics company the platform chrome over its own
// unchanged data. Nothing in the client may write either field.
export function isDeliveryPlatform() {
  const { tenant } = appStore.get();
  return tenant?.customer_type === 'DELIVERY_PLATFORM';
}

export function isLogisticsCompany() {
  return !isDeliveryPlatform();
}

/** Does this account have the capability the server granted it? */
export function can(capability) {
  const caps = appStore.get().tenant?.capabilities;
  return Array.isArray(caps) && caps.includes(capability);
}

