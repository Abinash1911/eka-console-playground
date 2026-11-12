import {
  init_compat_module,
  mn
} from "./chunk-MBQVUANQ.js";
import {
  k
} from "./chunk-3MQGPNVX.js";
import "./chunk-V4OQ3NZ2.js";

// node_modules/markdown-to-jsx/dist/index.modern.js
init_compat_module();
function n() {
  return n = Object.assign ? Object.assign.bind() : function(e) {
    for (var n2 = 1; n2 < arguments.length; n2++) {
      var r2 = arguments[n2];
      for (var t2 in r2) Object.prototype.hasOwnProperty.call(r2, t2) && (e[t2] = r2[t2]);
    }
    return e;
  }, n.apply(this, arguments);
}
var r = ["children", "options"];
var t = { blockQuote: "0", breakLine: "1", breakThematic: "2", codeBlock: "3", codeFenced: "4", codeInline: "5", footnote: "6", footnoteReference: "7", gfmTask: "8", heading: "9", headingSetext: "10", htmlBlock: "11", htmlComment: "12", htmlSelfClosing: "13", image: "14", link: "15", linkAngleBraceStyleDetector: "16", linkBareUrlDetector: "17", linkMailtoDetector: "18", newlineCoalescer: "19", orderedList: "20", paragraph: "21", ref: "22", refImage: "23", refLink: "24", table: "25", tableSeparator: "26", text: "27", textBolded: "28", textEmphasized: "29", textEscaped: "30", textMarked: "31", textStrikethroughed: "32", unorderedList: "33" };
var o = ["allowFullScreen", "allowTransparency", "autoComplete", "autoFocus", "autoPlay", "cellPadding", "cellSpacing", "charSet", "classId", "colSpan", "contentEditable", "contextMenu", "crossOrigin", "encType", "formAction", "formEncType", "formMethod", "formNoValidate", "formTarget", "frameBorder", "hrefLang", "inputMode", "keyParams", "keyType", "marginHeight", "marginWidth", "maxLength", "mediaGroup", "minLength", "noValidate", "radioGroup", "readOnly", "rowSpan", "spellCheck", "srcDoc", "srcLang", "srcSet", "tabIndex", "useMap"].reduce((e, n2) => (e[n2.toLowerCase()] = n2, e), { class: "className", for: "htmlFor" });
var a = { amp: "&", apos: "'", gt: ">", lt: "<", nbsp: " ", quot: "“" };
var c = ["style", "script", "pre"];
var i = ["src", "href", "data", "formAction", "srcDoc", "action"];
var u = /([-A-Z0-9_:]+)(?:\s*=\s*(?:(?:"((?:\\.|[^"])*)")|(?:'((?:\\.|[^'])*)')|(?:\{((?:\\.|{[^}]*?}|[^}])*)\})))?/gi;
var l = /\n{2,}$/;
var s = /^(\s*>[\s\S]*?)(?=\n\n|$)/;
var f = /^ *> ?/gm;
var _ = /^(?:\[!([^\]]*)\]\n)?([\s\S]*)/;
var d = /^ {2,}\n/;
var p = /^(?:([-*_])( *\1){2,}) *(?:\n *)+\n/;
var y = /^(?: {1,3})?(`{3,}|~{3,}) *(\S+)? *([^\n]*?)?\n([\s\S]*?)(?:\1\n?|$)/;
var h = /^(?: {4}[^\n]+\n*)+(?:\n *)+\n?/;
var g = /^(`+)((?:\\`|(?!\1)`|[^`])+)\1/;
var m = /^(?:\n *)*\n/;
var k2 = /\r\n?/g;
var x = /^\[\^([^\]]+)](:(.*)((\n+ {4,}.*)|(\n(?!\[\^).+))*)/;
var q = /^\[\^([^\]]+)]/;
var v = /\f/g;
var b = /^---[ \t]*\n(.|\n)*\n---[ \t]*\n/;
var $ = /^\s*?\[(x|\s)\]/;
var S = /^ *(#{1,6}) *([^\n]+?)(?: +#*)?(?:\n *)*(?:\n|$)/;
var z = /^ *(#{1,6}) +([^\n]+?)(?: +#*)?(?:\n *)*(?:\n|$)/;
var E = /^([^\n]+)\n *(=|-)\2{2,} *\n/;
var A = /^ *(?!<[a-z][^ >/]* ?\/>)<([a-z][^ >/]*) ?((?:[^>]*[^/])?)>\n?(\s*(?:<\1[^>]*?>[\s\S]*?<\/\1>|(?!<\1\b)[\s\S])*?)<\/\1>(?!<\/\1>)\n*/i;
var R = /&([a-z0-9]+|#[0-9]{1,6}|#x[0-9a-fA-F]{1,6});/gi;
var B = /^<!--[\s\S]*?(?:-->)/;
var L = /^(data|aria|x)-[a-z_][a-z\d_.-]*$/;
var O = /^ *<([a-z][a-z0-9:]*)(?:\s+((?:<.*?>|[^>])*))?\/?>(?!<\/\1>)(\s*\n)?/i;
var j = /^\{.*\}$/;
var C = /^(https?:\/\/[^\s<]+[^<.,:;"')\]\s])/;
var I = /^<([^ >]+[:@\/][^ >]+)>/;
var T = /-([a-z])?/gi;
var M = /^(\|.*)\n(?: *(\|? *[-:]+ *\|[-| :]*)\n((?:.*\|.*\n)*))?\n?/;
var w = /^[^\n]+(?:  \n|\n{2,})/;
var D = /^\[([^\]]*)\]:\s+<?([^\s>]+)>?\s*("([^"]*)")?/;
var F = /^!\[([^\]]*)\] ?\[([^\]]*)\]/;
var P = /^\[([^\]]*)\] ?\[([^\]]*)\]/;
var Z = /(\n|^[-*]\s|^#|^ {2,}|^-{2,}|^>\s)/;
var N = /\t/g;
var G = /(^ *\||\| *$)/g;
var U = /^ *:-+: *$/;
var V = /^ *:-+ *$/;
var H = /^ *-+: *$/;
var Q = (e) => `(?=[\\s\\S]+?\\1${e ? "\\1" : ""})`;
var W = "((?:\\[.*?\\][([].*?[)\\]]|<.*?>(?:.*?<.*?>)?|`.*?`|\\\\\\1|[\\s\\S])+?)";
var J = RegExp(`^([*_])\\1${Q(1)}${W}\\1\\1(?!\\1)`);
var K = RegExp(`^([*_])${Q(0)}${W}\\1(?!\\1)`);
var X = RegExp(`^(==)${Q(0)}${W}\\1`);
var Y = RegExp(`^(~~)${Q(0)}${W}\\1`);
var ee = /^(:[a-zA-Z0-9-_]+:)/;
var ne = /^\\([^0-9A-Za-z\s])/;
var re = /\\([^0-9A-Za-z\s])/g;
var te = /^[\s\S](?:(?!  \n|[0-9]\.|http)[^=*_~\-\n:<`\\\[!])*/;
var oe = /^\n+/;
var ae = /^([ \t]*)/;
var ce = /(?:^|\n)( *)$/;
var ie = "(?:\\d+\\.)";
var ue = "(?:[*+-])";
function le(e) {
  return "( *)(" + (1 === e ? ie : ue) + ") +";
}
var se = le(1);
var fe = le(2);
function _e(e) {
  return RegExp("^" + (1 === e ? se : fe));
}
var de = _e(1);
var pe = _e(2);
function ye(e) {
  return RegExp("^" + (1 === e ? se : fe) + "[^\\n]*(?:\\n(?!\\1" + (1 === e ? ie : ue) + " )[^\\n]*)*(\\n|$)", "gm");
}
var he = ye(1);
var ge = ye(2);
function me(e) {
  const n2 = 1 === e ? ie : ue;
  return RegExp("^( *)(" + n2 + ") [\\s\\S]+?(?:\\n{2,}(?! )(?!\\1" + n2 + " (?!" + n2 + " ))\\n*|\\s*\\n*$)");
}
var ke = me(1);
var xe = me(2);
function qe(e, n2) {
  const r2 = 1 === n2, t2 = r2 ? ke : xe, o2 = r2 ? he : ge, a2 = r2 ? de : pe;
  return { t: (e2) => a2.test(e2), o: je(function(e2, n3) {
    const r3 = ce.exec(n3.prevCapture);
    return r3 && (n3.list || !n3.inline && !n3.simple) ? t2.exec(e2 = r3[1] + e2) : null;
  }), i: 1, u(e2, n3, t3) {
    const c2 = r2 ? +e2[2] : void 0, i2 = e2[0].replace(l, "\n").match(o2);
    let u2 = false;
    return { items: i2.map(function(e3, r3) {
      const o3 = a2.exec(e3)[0].length, c3 = RegExp("^ {1," + o3 + "}", "gm"), l2 = e3.replace(c3, "").replace(a2, ""), s2 = r3 === i2.length - 1, f2 = -1 !== l2.indexOf("\n\n") || s2 && u2;
      u2 = f2;
      const _2 = t3.inline, d2 = t3.list;
      let p2;
      t3.list = true, f2 ? (t3.inline = false, p2 = Se(l2) + "\n\n") : (t3.inline = true, p2 = Se(l2));
      const y2 = n3(p2, t3);
      return t3.inline = _2, t3.list = d2, y2;
    }), ordered: r2, start: c2 };
  }, l: (n3, r3, t3) => e(n3.ordered ? "ol" : "ul", { key: t3.key, start: "20" === n3.type ? n3.start : void 0 }, n3.items.map(function(n4, o3) {
    return e("li", { key: o3 }, r3(n4, t3));
  })) };
}
var ve = RegExp(`^\\[((?:\\[[^\\[\\]]*(?:\\[[^\\[\\]]*\\][^\\[\\]]*)*\\]|[^\\[\\]])*)\\]\\(\\s*<?((?:\\([^)]*\\)|[^\\s\\\\]|\\\\.)*?)>?(?:\\s+['"]([\\s\\S]*?)['"])?\\s*\\)`);
var be = /^!\[(.*?)\]\( *((?:\([^)]*\)|[^() ])*) *"?([^)"]*)?"?\)/;
function $e(e) {
  return "string" == typeof e;
}
function Se(e) {
  let n2 = e.length;
  for (; n2 > 0 && e[n2 - 1] <= " "; ) n2--;
  return e.slice(0, n2);
}
function ze(e, n2) {
  return e.startsWith(n2);
}
function Ee(e, n2, r2) {
  if (Array.isArray(r2)) {
    for (let n3 = 0; n3 < r2.length; n3++) if (ze(e, r2[n3])) return true;
    return false;
  }
  return r2(e, n2);
}
function Ae(e) {
  return e.replace(/[ÀÁÂÃÄÅàáâãäåæÆ]/g, "a").replace(/[çÇ]/g, "c").replace(/[ðÐ]/g, "d").replace(/[ÈÉÊËéèêë]/g, "e").replace(/[ÏïÎîÍíÌì]/g, "i").replace(/[Ññ]/g, "n").replace(/[øØœŒÕõÔôÓóÒò]/g, "o").replace(/[ÜüÛûÚúÙù]/g, "u").replace(/[ŸÿÝý]/g, "y").replace(/[^a-z0-9- ]/gi, "").replace(/ /gi, "-").toLowerCase();
}
function Re(e) {
  return H.test(e) ? "right" : U.test(e) ? "center" : V.test(e) ? "left" : null;
}
function Be(e, n2, r2, t2) {
  const o2 = r2.inTable;
  r2.inTable = true;
  let a2 = [[]], c2 = "";
  function i2() {
    if (!c2) return;
    const e2 = a2[a2.length - 1];
    e2.push.apply(e2, n2(c2, r2)), c2 = "";
  }
  return e.trim().split(/(`[^`]*`|\\\||\|)/).filter(Boolean).forEach((e2, n3, r3) => {
    "|" === e2.trim() && (i2(), t2) ? 0 !== n3 && n3 !== r3.length - 1 && a2.push([]) : c2 += e2;
  }), i2(), r2.inTable = o2, a2;
}
function Le(e, n2, r2) {
  r2.inline = true;
  const t2 = e[2] ? e[2].replace(G, "").split("|").map(Re) : [], o2 = e[3] ? (function(e2, n3, r3) {
    return e2.trim().split("\n").map(function(e3) {
      return Be(e3, n3, r3, true);
    });
  })(e[3], n2, r2) : [], a2 = Be(e[1], n2, r2, !!o2.length);
  return r2.inline = false, o2.length ? { align: t2, cells: o2, header: a2, type: "25" } : { children: a2, type: "21" };
}
function Oe(e, n2) {
  return null == e.align[n2] ? {} : { textAlign: e.align[n2] };
}
function je(e) {
  return e.inline = 1, e;
}
function Ce(e) {
  return je(function(n2, r2) {
    return r2.inline ? e.exec(n2) : null;
  });
}
function Ie(e) {
  return je(function(n2, r2) {
    return r2.inline || r2.simple ? e.exec(n2) : null;
  });
}
function Te(e) {
  return function(n2, r2) {
    return r2.inline || r2.simple ? null : e.exec(n2);
  };
}
function Me(e) {
  return je(function(n2) {
    return e.exec(n2);
  });
}
var we = /(javascript|vbscript|data(?!:image)):/i;
function De(e) {
  try {
    const n2 = decodeURIComponent(e).replace(/[^A-Za-z0-9/:]/g, "");
    if (we.test(n2)) return null;
  } catch (e2) {
    return null;
  }
  return e;
}
function Fe(e) {
  return e ? e.replace(re, "$1") : e;
}
function Pe(e, n2, r2) {
  const t2 = r2.inline || false, o2 = r2.simple || false;
  r2.inline = true, r2.simple = true;
  const a2 = e(n2, r2);
  return r2.inline = t2, r2.simple = o2, a2;
}
function Ze(e, n2, r2) {
  const t2 = r2.inline || false, o2 = r2.simple || false;
  r2.inline = false, r2.simple = true;
  const a2 = e(n2, r2);
  return r2.inline = t2, r2.simple = o2, a2;
}
function Ne(e, n2, r2) {
  const t2 = r2.inline || false;
  r2.inline = false;
  const o2 = e(n2, r2);
  return r2.inline = t2, o2;
}
var Ge = (e, n2, r2) => ({ children: Pe(n2, e[2], r2) });
function Ue() {
  return {};
}
function Ve() {
  return null;
}
function He(...e) {
  return e.filter(Boolean).join(" ");
}
function Qe(e, n2, r2) {
  let t2 = e;
  const o2 = n2.split(".");
  for (; o2.length && (t2 = t2[o2[0]], void 0 !== t2); ) o2.shift();
  return t2 || r2;
}
function We(r2 = "", t2 = {}) {
  t2.overrides = t2.overrides || {}, t2.namedCodesToUnicode = t2.namedCodesToUnicode ? n({}, a, t2.namedCodesToUnicode) : a;
  const l2 = t2.slugify || Ae, G2 = t2.sanitizer || De, U2 = t2.createElement || k, V2 = [s, y, h, t2.enforceAtxHeadings ? z : S, E, M, ke, xe], H2 = [...V2, w, A, B, O];
  function Q2(e, n2) {
    for (let r3 = 0; r3 < e.length; r3++) if (e[r3].test(n2)) return true;
    return false;
  }
  function W2(e, r3, ...o2) {
    const a2 = Qe(t2.overrides, e + ".props", {});
    return U2((function(e2, n2) {
      const r4 = Qe(n2, e2);
      return r4 ? "function" == typeof r4 || "object" == typeof r4 && "render" in r4 ? r4 : Qe(n2, e2 + ".component", e2) : e2;
    })(e, t2.overrides), n({}, r3, a2, { className: He(null == r3 ? void 0 : r3.className, a2.className) || void 0 }), ...o2);
  }
  function re2(e) {
    e = e.replace(b, "");
    let n2 = false;
    t2.forceInline ? n2 = true : t2.forceBlock || (n2 = false === Z.test(e));
    const r3 = fe2(se2(n2 ? e : Se(e).replace(oe, "") + "\n\n", { inline: n2 }));
    for (; $e(r3[r3.length - 1]) && !r3[r3.length - 1].trim(); ) r3.pop();
    if (null === t2.wrapper) return r3;
    const o2 = t2.wrapper || (n2 ? "span" : "div");
    let a2;
    if (r3.length > 1 || t2.forceWrapper) a2 = r3;
    else {
      if (1 === r3.length) return a2 = r3[0], "string" == typeof a2 ? W2("span", { key: "outer" }, a2) : a2;
      a2 = null;
    }
    return U2(o2, { key: "outer" }, a2);
  }
  function ce2(e, n2) {
    if (!n2 || !n2.trim()) return null;
    const r3 = n2.match(u);
    return r3 ? r3.reduce(function(n3, r4) {
      const t3 = r4.indexOf("=");
      if (-1 !== t3) {
        const a2 = (function(e2) {
          return -1 !== e2.indexOf("-") && null === e2.match(L) && (e2 = e2.replace(T, function(e3, n4) {
            return n4.toUpperCase();
          })), e2;
        })(r4.slice(0, t3)).trim(), c2 = (function(e2) {
          const n4 = e2[0];
          return ('"' === n4 || "'" === n4) && e2.length >= 2 && e2[e2.length - 1] === n4 ? e2.slice(1, -1) : e2;
        })(r4.slice(t3 + 1).trim()), u2 = o[a2] || a2;
        if ("ref" === u2) return n3;
        const l3 = n3[u2] = (function(e2, n4, r5, t4) {
          return "style" === n4 ? (function(e3) {
            const n5 = [];
            let r6 = "", t5 = false, o2 = false, a3 = "";
            if (!e3) return n5;
            for (let c4 = 0; c4 < e3.length; c4++) {
              const i2 = e3[c4];
              if ('"' !== i2 && "'" !== i2 || t5 || (o2 ? i2 === a3 && (o2 = false, a3 = "") : (o2 = true, a3 = i2)), "(" === i2 && r6.endsWith("url") ? t5 = true : ")" === i2 && t5 && (t5 = false), ";" !== i2 || o2 || t5) r6 += i2;
              else {
                const e4 = r6.trim();
                if (e4) {
                  const r7 = e4.indexOf(":");
                  if (r7 > 0) {
                    const t6 = e4.slice(0, r7).trim(), o3 = e4.slice(r7 + 1).trim();
                    n5.push([t6, o3]);
                  }
                }
                r6 = "";
              }
            }
            const c3 = r6.trim();
            if (c3) {
              const e4 = c3.indexOf(":");
              if (e4 > 0) {
                const r7 = c3.slice(0, e4).trim(), t6 = c3.slice(e4 + 1).trim();
                n5.push([r7, t6]);
              }
            }
            return n5;
          })(r5).reduce(function(n5, [r6, o2]) {
            return n5[r6.replace(/(-[a-z])/g, (e3) => e3[1].toUpperCase())] = t4(o2, e2, r6), n5;
          }, {}) : -1 !== i.indexOf(n4) ? t4(Fe(r5), e2, n4) : (r5.match(j) && (r5 = Fe(r5.slice(1, r5.length - 1))), "true" === r5 || "false" !== r5 && r5);
        })(e, a2, c2, G2);
        "string" == typeof l3 && (A.test(l3) || O.test(l3)) && (n3[u2] = re2(l3.trim()));
      } else "style" !== r4 && (n3[o[r4] || r4] = true);
      return n3;
    }, {}) : null;
  }
  const ie2 = [], ue2 = {}, le2 = { 0: { t: [">"], o: Te(s), i: 1, u(e, n2, r3) {
    const [, t3, o2] = e[0].replace(f, "").match(_);
    return { alert: t3, children: n2(o2, r3) };
  }, l(e, n2, r3) {
    const t3 = { key: r3.key };
    return e.alert && (t3.className = "markdown-alert-" + l2(e.alert.toLowerCase(), Ae), e.children.unshift({ attrs: {}, children: [{ type: "27", text: e.alert }], noInnerParse: true, type: "11", tag: "header" })), W2("blockquote", t3, n2(e.children, r3));
  } }, 1: { t: ["  "], o: Me(d), i: 1, u: Ue, l: (e, n2, r3) => W2("br", { key: r3.key }) }, 2: { t: ["--", "__", "**", "- ", "* ", "_ "], o: Te(p), i: 1, u: Ue, l: (e, n2, r3) => W2("hr", { key: r3.key }) }, 3: { t: ["    "], o: Te(h), i: 0, u: (e) => ({ lang: void 0, text: Fe(Se(e[0].replace(/^ {4}/gm, ""))) }), l: (e, r3, t3) => W2("pre", { key: t3.key }, W2("code", n({}, e.attrs, { className: e.lang ? "lang-" + e.lang : "" }), e.text)) }, 4: { t: ["```", "~~~"], o: Te(y), i: 0, u: (e) => ({ attrs: ce2("code", e[3] || ""), lang: e[2] || void 0, text: e[4], type: "3" }) }, 5: { t: ["`"], o: Ie(g), i: 3, u: (e) => ({ text: Fe(e[2]) }), l: (e, n2, r3) => W2("code", { key: r3.key }, e.text) }, 6: { t: ["[^"], o: Te(x), i: 0, u: (e) => (ie2.push({ footnote: e[2], identifier: e[1] }), {}), l: Ve }, 7: { t: ["[^"], o: Ce(q), i: 1, u: (e) => ({ target: "#" + l2(e[1], Ae), text: e[1] }), l: (e, n2, r3) => W2("a", { key: r3.key, href: G2(e.target, "a", "href") }, W2("sup", { key: r3.key }, e.text)) }, 8: { t: ["[ ]", "[x]"], o: Ce($), i: 1, u: (e) => ({ completed: "x" === e[1].toLowerCase() }), l: (e, n2, r3) => W2("input", { checked: e.completed, key: r3.key, readOnly: true, type: "checkbox" }) }, 9: { t: ["#"], o: Te(t2.enforceAtxHeadings ? z : S), i: 1, u: (e, n2, r3) => ({ children: Pe(n2, e[2], r3), id: l2(e[2], Ae), level: e[1].length }), l: (e, n2, r3) => W2("h" + e.level, { id: e.id, key: r3.key }, n2(e.children, r3)) }, 10: { t: (e) => {
    const n2 = e.indexOf("\n");
    return n2 > 0 && n2 < e.length - 1 && ("=" === e[n2 + 1] || "-" === e[n2 + 1]);
  }, o: Te(E), i: 1, u: (e, n2, r3) => ({ children: Pe(n2, e[1], r3), level: "=" === e[2] ? 1 : 2, type: "9" }) }, 11: { t: ["<"], o: Me(A), i: 1, u(e, n2, r3) {
    const [, t3] = e[3].match(ae), o2 = RegExp("^" + t3, "gm"), a2 = e[3].replace(o2, ""), i2 = Q2(H2, a2) ? Ne : Pe, u2 = e[1].toLowerCase(), l3 = -1 !== c.indexOf(u2), s2 = (l3 ? u2 : e[1]).trim(), f2 = { attrs: ce2(s2, e[2]), noInnerParse: l3, tag: s2 };
    if (r3.inAnchor = r3.inAnchor || "a" === u2, l3) f2.text = e[3];
    else {
      const e2 = r3.inHTML;
      r3.inHTML = true, f2.children = i2(n2, a2, r3), r3.inHTML = e2;
    }
    return r3.inAnchor = false, f2;
  }, l: (e, r3, t3) => W2(e.tag, n({ key: t3.key }, e.attrs), e.text || (e.children ? r3(e.children, t3) : "")) }, 13: { t: ["<"], o: Me(O), i: 1, u(e) {
    const n2 = e[1].trim();
    return { attrs: ce2(n2, e[2] || ""), tag: n2 };
  }, l: (e, r3, t3) => W2(e.tag, n({}, e.attrs, { key: t3.key })) }, 12: { t: ["<!--"], o: Me(B), i: 1, u: () => ({}), l: Ve }, 14: { t: ["!["], o: Ie(be), i: 1, u: (e) => ({ alt: Fe(e[1]), target: Fe(e[2]), title: Fe(e[3]) }), l: (e, n2, r3) => W2("img", { key: r3.key, alt: e.alt || void 0, title: e.title || void 0, src: G2(e.target, "img", "src") }) }, 15: { t: ["["], o: Ce(ve), i: 3, u: (e, n2, r3) => ({ children: Ze(n2, e[1], r3), target: Fe(e[2]), title: Fe(e[3]) }), l: (e, n2, r3) => W2("a", { key: r3.key, href: G2(e.target, "a", "href"), title: e.title }, n2(e.children, r3)) }, 16: { t: ["<"], o: Ce(I), i: 0, u(e) {
    let n2 = e[1], r3 = false;
    return -1 !== n2.indexOf("@") && -1 === n2.indexOf("//") && (r3 = true, n2 = n2.replace("mailto:", "")), { children: [{ text: n2, type: "27" }], target: r3 ? "mailto:" + n2 : n2, type: "15" };
  } }, 17: { t: (e, n2) => !n2.inAnchor && !t2.disableAutoLink && (ze(e, "http://") || ze(e, "https://")), o: Ce(C), i: 0, u: (e) => ({ children: [{ text: e[1], type: "27" }], target: e[1], title: void 0, type: "15" }) }, 20: qe(W2, 1), 33: qe(W2, 2), 19: { t: ["\n"], o: Te(m), i: 3, u: Ue, l: () => "\n" }, 21: { o: je(function(e, n2) {
    if (n2.inline || n2.simple || n2.inHTML && -1 === e.indexOf("\n\n") && -1 === n2.prevCapture.indexOf("\n\n")) return null;
    let r3 = "", t3 = 0;
    for (; ; ) {
      const n3 = e.indexOf("\n", t3), o3 = e.slice(t3, -1 === n3 ? void 0 : n3 + 1);
      if (Q2(V2, o3)) break;
      if (r3 += o3, -1 === n3 || !o3.trim()) break;
      t3 = n3 + 1;
    }
    const o2 = Se(r3);
    return "" === o2 ? null : [r3, , o2];
  }), i: 3, u: Ge, l: (e, n2, r3) => W2("p", { key: r3.key }, n2(e.children, r3)) }, 22: { t: ["["], o: Ce(D), i: 0, u: (e) => (ue2[e[1]] = { target: e[2], title: e[4] }, {}), l: Ve }, 23: { t: ["!["], o: Ie(F), i: 0, u: (e) => ({ alt: e[1] ? Fe(e[1]) : void 0, ref: e[2] }), l: (e, n2, r3) => ue2[e.ref] ? W2("img", { key: r3.key, alt: e.alt, src: G2(ue2[e.ref].target, "img", "src"), title: ue2[e.ref].title }) : null }, 24: { t: (e) => "[" === e[0] && -1 === e.indexOf("]("), o: Ce(P), i: 0, u: (e, n2, r3) => ({ children: n2(e[1], r3), fallbackChildren: e[0], ref: e[2] }), l: (e, n2, r3) => ue2[e.ref] ? W2("a", { key: r3.key, href: G2(ue2[e.ref].target, "a", "href"), title: ue2[e.ref].title }, n2(e.children, r3)) : W2("span", { key: r3.key }, e.fallbackChildren) }, 25: { t: ["|"], o: Te(M), i: 1, u: Le, l(e, n2, r3) {
    const t3 = e;
    return W2("table", { key: r3.key }, W2("thead", null, W2("tr", null, t3.header.map(function(e2, o2) {
      return W2("th", { key: o2, style: Oe(t3, o2) }, n2(e2, r3));
    }))), W2("tbody", null, t3.cells.map(function(e2, o2) {
      return W2("tr", { key: o2 }, e2.map(function(e3, o3) {
        return W2("td", { key: o3, style: Oe(t3, o3) }, n2(e3, r3));
      }));
    })));
  } }, 27: { o: je(function(e, n2) {
    let r3;
    return ze(e, ":") && (r3 = ee.exec(e)), r3 || te.exec(e);
  }), i: 4, u(e) {
    const n2 = e[0];
    return { text: -1 === n2.indexOf("&") ? n2 : n2.replace(R, (e2, n3) => t2.namedCodesToUnicode[n3] || e2) };
  }, l: (e) => e.text }, 28: { t: ["**", "__"], o: Ie(J), i: 2, u: (e, n2, r3) => ({ children: n2(e[2], r3) }), l: (e, n2, r3) => W2("strong", { key: r3.key }, n2(e.children, r3)) }, 29: { t: (e) => {
    const n2 = e[0];
    return ("*" === n2 || "_" === n2) && e[1] !== n2;
  }, o: Ie(K), i: 3, u: (e, n2, r3) => ({ children: n2(e[2], r3) }), l: (e, n2, r3) => W2("em", { key: r3.key }, n2(e.children, r3)) }, 30: { t: ["\\"], o: Ie(ne), i: 1, u: (e) => ({ text: e[1], type: "27" }) }, 31: { t: ["=="], o: Ie(X), i: 3, u: Ge, l: (e, n2, r3) => W2("mark", { key: r3.key }, n2(e.children, r3)) }, 32: { t: ["~~"], o: Ie(Y), i: 3, u: Ge, l: (e, n2, r3) => W2("del", { key: r3.key }, n2(e.children, r3)) } };
  true === t2.disableParsingRawHTML && (delete le2[11], delete le2[13]);
  const se2 = (function(e) {
    var n2 = Object.keys(e);
    function r3(t3, o2) {
      var a2 = [];
      if (o2.prevCapture = o2.prevCapture || "", t3.trim()) for (; t3; ) for (var c2 = 0; c2 < n2.length; ) {
        var i2 = n2[c2], u2 = e[i2];
        if (!u2.t || Ee(t3, o2, u2.t)) {
          var l3 = u2.o(t3, o2);
          if (l3 && l3[0]) {
            t3 = t3.substring(l3[0].length);
            var s2 = u2.u(l3, r3, o2);
            o2.prevCapture += l3[0], s2.type || (s2.type = i2), a2.push(s2);
            break;
          }
          c2++;
        } else c2++;
      }
      return o2.prevCapture = "", a2;
    }
    return n2.sort(function(n3, r4) {
      return e[n3].i - e[r4].i || (n3 < r4 ? -1 : 1);
    }), function(e2, n3) {
      return r3((function(e3) {
        return e3.replace(k2, "\n").replace(v, "").replace(N, "    ");
      })(e2), n3);
    };
  })(le2), fe2 = /* @__PURE__ */ (function(e, n2) {
    return function r3(t3, o2 = {}) {
      if (Array.isArray(t3)) {
        const e2 = o2.key, n3 = [];
        let a2 = false;
        for (let e3 = 0; e3 < t3.length; e3++) {
          o2.key = e3;
          const c2 = r3(t3[e3], o2), i2 = $e(c2);
          i2 && a2 ? n3[n3.length - 1] += c2 : null !== c2 && n3.push(c2), a2 = i2;
        }
        return o2.key = e2, n3;
      }
      return (function(r4, t4, o3) {
        const a2 = e[r4.type].l;
        return n2 ? n2(() => a2(r4, t4, o3), r4, t4, o3) : a2(r4, t4, o3);
      })(t3, r3, o2);
    };
  })(le2, t2.renderRule), _e2 = re2(r2);
  return ie2.length ? W2("div", null, _e2, W2("footer", { key: "footer" }, ie2.map(function(e) {
    return W2("div", { id: l2(e.identifier, Ae), key: e.identifier }, e.identifier, fe2(se2(e.footnote, { inline: true })));
  }))) : _e2;
}
var index_modern_default = (n2) => {
  let { children: t2, options: o2 } = n2, a2 = (function(e, n3) {
    if (null == e) return {};
    var r2, t3, o3 = {}, a3 = Object.keys(e);
    for (t3 = 0; t3 < a3.length; t3++) n3.indexOf(r2 = a3[t3]) >= 0 || (o3[r2] = e[r2]);
    return o3;
  })(n2, r);
  return mn(We(null == t2 ? "" : t2, o2), a2);
};
export {
  t as RuleType,
  We as compiler,
  index_modern_default as default,
  De as sanitizer,
  Ae as slugify
};
//# sourceMappingURL=markdown-to-jsx.js.map
