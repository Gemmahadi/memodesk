#!/usr/bin/env python3
"""Record the MemoDesk demo in a real browser (Playwright + system Chrome).

Flow (all real: the page talks to the live backend, which talks to live Meko):
  0. load app, screenshot inbox
  1. Reset demo (fresh datapack) -> Seed Meko datapack
  2. Triage TKT-1001 (duplicate charge, Acme) -> screenshot result
  3. Resolve TKT-1001, remembering the outcome in Meko
  4. Triage TKT-1002 (same customer follow-up) -> screenshot: recall proof
  5. Shared-memory + audit panels -> screenshot
Writes: shots/*.png, video raw webm, steps.json (timestamps for captions).
"""
import json
import os
import time

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "shots")
VID = os.path.join(HERE, "video")
os.makedirs(SHOTS, exist_ok=True)
os.makedirs(VID, exist_ok=True)

URL = "http://127.0.0.1:8899/"
CHROME = os.path.expanduser("~/workspace/chrome-real/opt/google/chrome/chrome")


def main():
    steps = []
    t0 = time.time()

    def mark(label):
        steps.append({"t": round(time.time() - t0, 1), "label": label})
        print(f"[{time.time()-t0:5.1f}s] {label}")

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME,
                                    args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 1280, "height": 800},
                                  record_video_dir=VID,
                                  record_video_size={"width": 1280, "height": 800})
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        page.goto(URL)
        page.wait_for_selector("#inbox .ticket", timeout=30000)
        time.sleep(1)
        mark("MemoDesk — support triage with Meko shared memory")
        page.screenshot(path=os.path.join(SHOTS, "01-inbox.png"))

        mark("Step 1: Reset demo — fresh Meko datapack, seed memory + knowledge base")
        page.click("#resetBtn")
        page.wait_for_function(
            "document.getElementById('health').textContent.includes('seeded: true')",
            timeout=180000)
        time.sleep(1)
        page.screenshot(path=os.path.join(SHOTS, "02-seeded.png"))

        mark("Step 2: Triage TKT-1001 — Meko recalls Acme's store-credit preference")
        page.click("text=TKT-1001")
        page.click("text=Run triage on selected ticket")
        page.wait_for_selector("#triage pre", timeout=120000)
        time.sleep(1)
        page.screenshot(path=os.path.join(SHOTS, "03-triage-1001.png"))

        mark("Step 3: Resolve — outcome stored as shared memory in Meko")
        page.fill("#res", "Duplicate $149 refunded as store credit.")
        page.click("text=Resolve & remember in Meko")
        page.wait_for_function(
            "document.getElementById('triage').textContent.includes('Resolved')",
            timeout=120000)
        time.sleep(1)

        mark("Step 4: Follow-up ticket TKT-1002 — the agent recalls the earlier resolution")
        page.click("text=TKT-1002")
        page.click("text=Run triage on selected ticket")
        page.wait_for_function(
            "document.getElementById('triage').textContent.includes('Resolved TKT-1001')",
            timeout=120000)
        time.sleep(1)
        page.screenshot(path=os.path.join(SHOTS, "04-recall-1002.png"))

        mark("Step 5: Shared memory + audit trail — every Meko call logged")
        page.click("#memBtn")
        page.click("#auditBtn")
        page.wait_for_function(
            "document.getElementById('audit').textContent.includes('context_search')",
            timeout=60000)
        time.sleep(1)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        page.screenshot(path=os.path.join(SHOTS, "05-memory-audit.png"))
        page.evaluate("window.scrollTo(0, 0)")

        mark("Done — real Meko calls, real recall, no mocks")
        time.sleep(1)
        ctx.close()
        browser.close()

    json.dump({"steps": steps, "duration": round(time.time() - t0, 1)},
              open(os.path.join(HERE, "steps.json"), "w"), indent=1)
    print("steps:", json.dumps(steps, indent=1))


if __name__ == "__main__":
    main()
