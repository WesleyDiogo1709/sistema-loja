export const state = { me: null, perms: new Set(), settings: {}, methods: [], cashOpen: false };
export const can = (p) => state.perms.has(p);
export const canAny = (...p) => p.some((x) => state.perms.has(x));
export const methodLabel = (key) => (state.methods.find((m) => m.key === key) || {}).label || key;
