# AGENTS.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## Project Notes

Bluefin Niri builds Fedora Atomic bootc images with Niri. Bluefin and Bazzite variants use DankMaterialShell (DMS); `fedora-44-niri` uses Noctalia on Fedora Sway Atomic 44.

Build commands:
```bash
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bluefin-dx --build-arg VARIANT=bluefin-niri -t bluefin-niri:test .
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bluefin-dx-nvidia-open --build-arg VARIANT=bluefin-niri-nvidia -t bluefin-niri-nvidia:test .
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bazzite --build-arg VARIANT=bazzite-niri -t bazzite-niri:test .
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bazzite-nvidia --build-arg VARIANT=bazzite-niri-nvidia -t bazzite-niri-nvidia:test .
podman build --build-arg BASE_IMAGE=quay.io/fedora/fedora-sway-atomic --build-arg TAG=44 --build-arg VARIANT=fedora-44-niri -t fedora-44-niri:test .
```

Variant notes:
- `system_files/` is staged at `/tmp/system_files`; `build.sh` only copies it for non-Fedora variants.
- `fedora-44-niri` skips uBlue `ujust` files and ThinkPad fan defaults.
- `fedora-44-niri` installs Noctalia from Terra, disables Terra after install, seeds SDDM to `niri.desktop`, and keeps Sway selectable as a fallback.
- Existing Bluefin/Bazzite variants keep the COPR-based DMS path and existing service presets.
