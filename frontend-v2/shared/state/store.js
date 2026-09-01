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

export function isDeliveryPlatform() {
  const { tenant } = appStore.get();
  return tenant?.customer_type === 'DELIVERY_PLATFORM';
}

export function isLogisticsCompany() {
  return !isDeliveryPlatform();
}

