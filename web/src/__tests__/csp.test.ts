/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";
import widgetsIndex from "@cesium/widgets/index.js?raw";
import { INDEX_HTML, SOURCES, findAll, type Hit } from "./fixtures/sources";

/**
 * The node serves the console under `default-src 'self'` with
 * `script-src 'self' 'wasm-unsafe-eval'` (sentinel/api/app.py). Code that
 * needs an external origin, an inline script or handler, or JavaScript
 * eval would be blocked in the field, on a network with no route out.
 * These checks read the console's source and fail on any of them.
 */

const RULES: { name: string; pattern: RegExp }[] = [
  // XML namespace names are identifiers, not fetches.
  { name: "external origin", pattern: /\bhttps?:\/\/(?!www\.w3\.org\/(?:2000\/svg|1999\/xlink)\b)[^\s"'`)]+/g },
  { name: "protocol-relative URL", pattern: /(?:\b(?:src|href)\s*=\s*\{?\s*|\burl\(\s*)["'`]?\/\/[^\s"'`)]+/g },
  { name: "eval", pattern: /(?<![\w$.])(?:eval|Function)\s*\(/g },
  { name: "string timer", pattern: /\bset(?:Timeout|Interval)\(\s*["'`]/g },
  { name: "HTML sink", pattern: /dangerouslySetInnerHTML|\.(?:inner|outer)HTML\s*=|insertAdjacentHTML|document\.write/g },
  { name: "javascript: URL", pattern: /javascript:/gi },
  { name: "inline event handler", pattern: /setAttribute\(\s*["'`]on|["'`][^"'`\n]*<[a-z][^"'`\n]*\son[a-z]+\s*=/gi },
];

function cspProblems(file: string, text: string): (Hit & { rule: string })[] {
  return RULES.flatMap(({ name, pattern }) => findAll(file, text, pattern).map((hit) => ({ ...hit, rule: name })));
}

/** An inline <script> (no src), or an on* attribute, in a page. */
function inlineScriptProblems(file: string, html: string): Hit[] {
  return [
    ...findAll(file, html, /<script\b(?![^>]*\bsrc=)[^>]*>/gi),
    ...findAll(file, html, /<[a-z][^>]*\son[a-z]+\s*=/gi),
  ];
}

/** Names a source imports from "cesium". */
function cesiumImports(text: string): string[] {
  return [...text.matchAll(/import\s*\{([^}]*)\}\s*from\s*["']cesium["']/g)].flatMap((m) =>
    m[1]
      .split(",")
      .map((name) => name.trim().replace(/^type\s+/, "").split(/\s+as\s+/)[0])
      .filter(Boolean),
  );
}

describe("the CSP checks catch what they are for", () => {
  it.each([
    ["external origin", `fetch("https://tile.example.com/0/0/0.png")`],
    ["external origin", `@import url(http://fonts.example.com/x.css);`],
    ["protocol-relative URL", `<img src="//cdn.example.com/a.png" />`],
    ["eval", `const f = new Function("return 1");`],
    ["eval", `eval(code)`],
    ["string timer", `setTimeout("tick()", 10)`],
    ["HTML sink", `<div dangerouslySetInnerHTML={{ __html: text }} />`],
    ["HTML sink", `node.innerHTML = text`],
    ["javascript: URL", `<a href={"javascript:void(0)"}>x</a>`],
    ["inline event handler", `el.setAttribute("onclick", handler)`],
    ["inline event handler", `const html = "<img src=x onerror=alert(1)>";`],
  ])("flags %s in %s", (rule, code) => {
    expect(cspProblems("x.tsx", code).map((p) => p.rule)).toContain(rule);
  });

  it("leaves React handlers, SVG namespaces and same-origin paths alone", () => {
    const code = [
      `<button onClick={() => setOpen(true)}>`,
      `<svg xmlns="http://www.w3.org/2000/svg">`,
      `fetch("/api/node")`,
      `new EventSource("/api/stream")`,
      `buildModuleUrl("Assets/Textures/NaturalEarthII")`,
      `fill={\`url(#\${hatch})\`}`,
      `const addFunction = x.requestFunction();`,
    ].join("\n");
    expect(cspProblems("x.tsx", code)).toEqual([]);
  });

  it("flags an inline script or handler in a page", () => {
    expect(inlineScriptProblems("x.html", `<script>boot()</script>`)).toHaveLength(1);
    expect(inlineScriptProblems("x.html", `<body onload="boot()">`)).toHaveLength(1);
    expect(inlineScriptProblems("x.html", `<script type="module" src="/src/main.tsx"></script>`)).toEqual([]);
  });

  it("reads the names imported from cesium", () => {
    expect(cesiumImports(`import {\n  ArcType,\n  Viewer as V,\n  type Entity,\n} from "cesium";`)).toEqual(["ArcType", "Viewer", "Entity"]);
  });
});

describe("the console's source meets the node's Content-Security-Policy", () => {
  it("fetches only from its own node, and has no eval, HTML sink or inline handler", () => {
    const problems = Object.entries(SOURCES).flatMap(([file, text]) => cspProblems(file, text));
    expect(problems).toEqual([]);
  });

  it("index.html loads its script from a file and has no inline script or handler", () => {
    expect(inlineScriptProblems("index.html", INDEX_HTML)).toEqual([]);
    expect(cspProblems("index.html", INDEX_HTML)).toEqual([]);
  });

  it("uses no Cesium widget: widgets compile Knockout bindings with Function(), which script-src blocks", () => {
    const widgets = new Set([...widgetsIndex.matchAll(/export\s*\{\s*default\s+as\s+(\w+)\s*\}/g)].map((m) => m[1]));
    expect(widgets.has("Viewer")).toBe(true); // the list was read
    const used = Object.entries(SOURCES).flatMap(([file, text]) => cesiumImports(text).map((name) => `${file}: ${name}`));
    expect(used.length).toBeGreaterThan(0);
    expect(used.filter((entry) => widgets.has(entry.split(": ")[1]))).toEqual([]);
  });
});
