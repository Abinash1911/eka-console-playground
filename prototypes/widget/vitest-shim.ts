// The repo's MockSynapseSDK uses vitest's `vi.fn`; in a browser we only need a pass-through.
export const vi = { fn: <T>(impl?: T) => impl ?? (() => undefined) };
