import { expect } from "vitest";

/**
 * Strings an attacker controls: object names and originators in an
 * uploaded CDM, AI answer text, server error details, sync event ids, a
 * peer node's log entries. Each would run script if it reached the DOM as
 * markup or as an attribute; the console must show every one as text.
 */
export const HOSTILE = {
  script: "<script>window.__pwned = 'script'</script>",
  img: `<img src=x onerror="window.__pwned = 'img'">`,
  svg: "<svg onload=\"window.__pwned = 'svg'\"></svg>",
  attr: `" autofocus onfocus="window.__pwned = 'attr'`,
  url: "javascript:window.__pwned = 'url'",
} as const;

const ACTIVE_ELEMENTS = "script, img, iframe, object, embed, foreignObject, link, meta, base";

/** Every payload arrived as literal text, and nothing it carried became an
 *  element, an event handler or a script URL. */
export function expectInert(container: HTMLElement, shown: string[]): void {
  const text = container.textContent ?? "";
  for (const payload of shown) expect(text).toContain(payload);
  expect(container.querySelectorAll(ACTIVE_ELEMENTS)).toHaveLength(0);
  for (const element of container.querySelectorAll("*")) {
    for (const { name, value } of element.attributes) {
      expect(name, `event handler attribute on <${element.tagName}>`).not.toMatch(/^on/i);
      if (/^(href|src|xlink:href|action|formaction)$/i.test(name)) expect(value).not.toMatch(/^\s*javascript:/i);
    }
  }
  expect((window as { __pwned?: unknown }).__pwned).toBeUndefined();
}
