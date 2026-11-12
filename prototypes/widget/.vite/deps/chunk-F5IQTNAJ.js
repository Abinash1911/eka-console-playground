import {
  composeRefs
} from "./chunk-MSDH66L5.js";
import {
  D,
  L,
  compat_module_exports,
  hn,
  init_compat_module,
  mn
} from "./chunk-MBQVUANQ.js";
import {
  u
} from "./chunk-VIFQTEGR.js";
import {
  S
} from "./chunk-3MQGPNVX.js";

// node_modules/@radix-ui/react-slot/dist/index.mjs
init_compat_module();
var REACT_LAZY_TYPE = Symbol.for("react.lazy");
var use = compat_module_exports[" use ".trim().toString()];
function isPromiseLike(value) {
  return typeof value === "object" && value !== null && "then" in value;
}
function isLazyComponent(element) {
  return element != null && typeof element === "object" && "$$typeof" in element && element.$$typeof === REACT_LAZY_TYPE && "_payload" in element && isPromiseLike(element._payload);
}
function createSlot(ownerName) {
  const SlotClone = createSlotClone(ownerName);
  const Slot2 = D((props, forwardedRef) => {
    let { children, ...slotProps } = props;
    if (isLazyComponent(children) && typeof use === "function") {
      children = use(children._payload);
    }
    const childrenArray = L.toArray(children);
    const slottable = childrenArray.find(isSlottable);
    if (slottable) {
      const newElement = slottable.props.children;
      const newChildren = childrenArray.map((child) => {
        if (child === slottable) {
          if (L.count(newElement) > 1) return L.only(null);
          return hn(newElement) ? newElement.props.children : null;
        } else {
          return child;
        }
      });
      return u(SlotClone, { ...slotProps, ref: forwardedRef, children: hn(newElement) ? mn(newElement, void 0, newChildren) : null });
    }
    return u(SlotClone, { ...slotProps, ref: forwardedRef, children });
  });
  Slot2.displayName = `${ownerName}.Slot`;
  return Slot2;
}
var Slot = createSlot("Slot");
function createSlotClone(ownerName) {
  const SlotClone = D((props, forwardedRef) => {
    let { children, ...slotProps } = props;
    if (isLazyComponent(children) && typeof use === "function") {
      children = use(children._payload);
    }
    if (hn(children)) {
      const childrenRef = getElementRef(children);
      const props2 = mergeProps(slotProps, children.props);
      if (children.type !== S) {
        props2.ref = forwardedRef ? composeRefs(forwardedRef, childrenRef) : childrenRef;
      }
      return mn(children, props2);
    }
    return L.count(children) > 1 ? L.only(null) : null;
  });
  SlotClone.displayName = `${ownerName}.SlotClone`;
  return SlotClone;
}
var SLOTTABLE_IDENTIFIER = Symbol("radix.slottable");
function createSlottable(ownerName) {
  const Slottable2 = ({ children }) => {
    return u(S, { children });
  };
  Slottable2.displayName = `${ownerName}.Slottable`;
  Slottable2.__radixId = SLOTTABLE_IDENTIFIER;
  return Slottable2;
}
var Slottable = createSlottable("Slottable");
function isSlottable(child) {
  return hn(child) && typeof child.type === "function" && "__radixId" in child.type && child.type.__radixId === SLOTTABLE_IDENTIFIER;
}
function mergeProps(slotProps, childProps) {
  const overrideProps = { ...childProps };
  for (const propName in childProps) {
    const slotPropValue = slotProps[propName];
    const childPropValue = childProps[propName];
    const isHandler = /^on[A-Z]/.test(propName);
    if (isHandler) {
      if (slotPropValue && childPropValue) {
        overrideProps[propName] = (...args) => {
          const result = childPropValue(...args);
          slotPropValue(...args);
          return result;
        };
      } else if (slotPropValue) {
        overrideProps[propName] = slotPropValue;
      }
    } else if (propName === "style") {
      overrideProps[propName] = { ...slotPropValue, ...childPropValue };
    } else if (propName === "className") {
      overrideProps[propName] = [slotPropValue, childPropValue].filter(Boolean).join(" ");
    }
  }
  return { ...slotProps, ...overrideProps };
}
function getElementRef(element) {
  let getter = Object.getOwnPropertyDescriptor(element.props, "ref")?.get;
  let mayWarn = getter && "isReactWarning" in getter && getter.isReactWarning;
  if (mayWarn) {
    return element.ref;
  }
  getter = Object.getOwnPropertyDescriptor(element, "ref")?.get;
  mayWarn = getter && "isReactWarning" in getter && getter.isReactWarning;
  if (mayWarn) {
    return element.props.ref;
  }
  return element.props.ref || element.ref;
}

export {
  createSlot,
  Slot,
  createSlottable,
  Slottable
};
//# sourceMappingURL=chunk-F5IQTNAJ.js.map
