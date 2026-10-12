"""Observable input in the same MCP browser, with explicit pointer provenance.

The model selects targets and values. This adapter only executes that selection;
it contains no workflow or company knowledge. Its fixed Playwright snippet is
not a model-visible arbitrary-code tool. Human mouse events never drive the overlay.
"""

from __future__ import annotations

import json
import re

TARGET = re.compile(r"^(f\d+)?e\d+$")
INPUTS = {"browser_click", "browser_type", "browser_select_option"}


def input_code(name: str, args: dict) -> str:
    target = args.get("target", "")
    if not isinstance(target, str) or not TARGET.fullmatch(target):
        raise ValueError("Use a current element ref from a fresh browser snapshot.")
    payload = json.dumps({**args, "name": name}, ensure_ascii=True)
    return (
        "async (page) => { const input = "
        + payload
        + ";"
        + r"""
      const locator = page.locator('aria-ref=' + input.target);
      if (input.name === 'browser_type') {
        const editable = await locator.evaluate(el =>
          (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)
          && !el.disabled && !el.readOnly);
        if (!editable) throw new Error('Target is not editable; take a fresh snapshot.');
      }
      const viewport = await page.evaluate(() => ({ width: innerWidth, height: innerHeight }));
      let box = await locator.boundingBox();
      if (!box) throw new Error('Target is not visible; take a fresh snapshot.');
      if (box.y < 60 || box.y + box.height > viewport.height - 90) {
        const distance = box.y + box.height / 2 - viewport.height / 2;
        for (let i = 0; i < 6; i++) {
          await page.mouse.wheel(0, distance / 6);
          await page.waitForTimeout(55);
        }
      }
      await locator.scrollIntoViewIfNeeded({ timeout: 4000 });
      box = await locator.boundingBox();
      if (!box) throw new Error('Target disappeared; take a fresh snapshot.');
      const destination = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
      // The overlay is decoration: missing or partial on some pages; input never needs it.
      const ava = (name, arg) => page.evaluate(([n, a]) => {
        const o = window.__ava;
        return o && typeof o[n] === 'function' ? o[n](a) : null;
      }, [name, arg]).catch(() => null);
      const start = (await ava('position')) || { x: 35, y: 80 };
      for (let i = 1; i <= 12; i++) {
        const point = { x: start.x + (destination.x - start.x) * i / 12,
                        y: start.y + (destination.y - start.y) * i / 12 };
        await page.mouse.move(point.x, point.y);
        await ava('move', point);
        await page.waitForTimeout(22);
      }
      if (input.name === 'browser_click') {
        if (input.button && input.button !== 'left')
          throw new Error('Only left clicks are supported in visible input.');
        const navigates = await locator.evaluate(el => Boolean(el.closest('a[href]')) ||
          Boolean(el.closest('form') &&
            ((el.tagName === 'BUTTON' && el.type === 'submit') ||
             (el.tagName === 'INPUT' && /submit|image/.test(el.type)))));
        const navigation = navigates ? page.waitForNavigation({
          waitUntil: 'domcontentloaded', timeout: 4000
        }).catch(() => null) : null;
        await page.mouse.click(destination.x, destination.y,
                               { clickCount: input.doubleClick ? 2 : 1 });
        if (navigation) await navigation;
        // A successful navigation can destroy the old document before the pulse.
        // Decorative overlay timing must never turn a real click into a failure.
        await ava('clicked');
      } else if (input.name === 'browser_type') {
        await page.mouse.click(destination.x, destination.y);
        await ava('clicked');
        const kind = await locator.evaluate(el => el.type || 'text');
        if (kind === 'date' || kind === 'datetime-local' || kind === 'time') {
          // Native segmented date controls need their format-aware input path.
          await locator.fill(input.text, { timeout: 4000 });
        } else {
          await page.keyboard.press('ControlOrMeta+a');
          await page.keyboard.press('Backspace');
          await page.keyboard.type(input.text, { delay: input.text.length > 100 ? 20 : 65 });
        }
        if (input.submit) await page.keyboard.press('Enter');
      } else if (input.name === 'browser_select_option') {
        if (input.values.length !== 1) throw new Error('Choose one option at a time.');
        const choice = await locator.evaluate((el, wanted) => {
          if (el.tagName !== 'SELECT') return null;
          const available = [...el.options].filter(o => !o.disabled);
          const index = available.findIndex(o => o.label === wanted || o.value === wanted);
          return index < 0 ? null : { value: available[index].value };
        }, input.values[0]);
        if (!choice)
          throw new Error('Option not found; copy its label from a fresh snapshot.');
        await page.mouse.click(destination.x, destination.y);
        await ava('clicked');
        await page.waitForTimeout(250);
        // OS-owned select popups do not consistently accept CDP keyboard input
        // on macOS. Use Playwright's native select input after showing the target.
        await page.keyboard.press('Escape');
        await locator.selectOption({ value: choice.value });
        if (await locator.inputValue() !== choice.value)
          throw new Error('Option was not selected; inspect the page before continuing.');
      }
      return { executed: input.name, target: input.target, pointer: destination,
               inputMode: 'visible',
               typing: input.name === 'browser_type' ? 'native-format-or-keystrokes' : null };
    }"""
    )
