import {
  A,
  T,
  init_compat_module,
  y
} from "./chunk-MBQVUANQ.js";

// node_modules/@radix-ui/react-use-callback-ref/dist/index.mjs
init_compat_module();
function useCallbackRef(callback) {
  const callbackRef = A(callback);
  y(() => {
    callbackRef.current = callback;
  });
  return T(() => (...args) => callbackRef.current?.(...args), []);
}

export {
  useCallbackRef
};
//# sourceMappingURL=chunk-ZKMMFECN.js.map
