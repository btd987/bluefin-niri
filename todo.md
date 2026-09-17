# Active Tasks

## Current Status

- [x] Replace the Fedora Firefox RPM with the Mozilla Flathub application used
  by the other desktop variants. Flatpak's OS preinstall mechanism installs it
  into mutable system storage on a connected boot instead of baking `/var` into
  the bootc image; an isolated real preinstall resolved Firefox 156.0 from the
  GPG-verified remote and confirmed the sandbox exposes all devices and PC/SC.
  The standard suite ran 226 tests: 205 passed, 21 opt-in tests skipped, and no
  tests failed locally. The first CI run exposed and then fixed an Ubuntu-only
  offline unit-test mock that covered `ExecStart` but not `ExecStartPre` or
  `ExecStartPost`. `bash -n build.sh` and `git diff --check` passed.
- [ ] Boot the updated Fedora image and verify first-boot Firefox installation,
  desktop launch, profile migration behavior, and Bitwarden FIDO2/WebAuthn with
  a physical YubiKey. Flatpak permission checks do not establish token access.
- [x] Add the Fedora English glibc language pack so `en_US.UTF-8` resolves
  instead of producing `LC_ALL`/`setlocale` missing-locale errors. The previous
  image reproduced the warning and exposed only `C`, `C.utf8`, and `POSIX`.
  The standard suite ran 225 tests: 204 passed, 21 opt-in tests skipped, and no
  tests failed. `bash -n build.sh` and `git diff --check` passed.
- [ ] Boot the locale-fixed Fedora image and confirm a login shell reports
  `en_US.UTF-8` without locale warnings.
- [x] Inspect the Fedora desktop package and Flatpak setup; Firefox and GNOME
  Software are available as Fedora 44 packages, while only the Flatpak CLI was
  previously present.
- [x] Add Firefox, GNOME Software and system-wide Flathub access to the Fedora
  testing variant. The standard suite ran 225 tests: 204 passed, 21 opt-in
  tests skipped, and no tests failed. `bash -n build.sh` and `git diff --check`
  passed.
- [x] Build the complete dependency chain and `localhost/fedora-niri:browser-test`
  image from Fedora base digest `sha256:c42272e0eed33a6eac747dbc6b1bd9f362f6a878183223ffbc6d5371dd4dc0fe`.
  Image ID `315d8da951ab` passed build-time package, exact-kernel ZFS and bootc
  validation with the existing bootc lint warnings.
- [x] Validate Firefox 155.0, GNOME Software 50.4, desktop launchers and the
  GNOME Software Flatpak plugin in the built image. The system Flathub remote
  resolved metadata and installed GNOME Sudoku in an ephemeral container.
- [ ] Boot the updated image and verify graphical Firefox and GNOME Software
  launch, Flatpak installation and update/rollback on hardware.
- [x] Preserve exact-kernel package installation when a floating Fedora base
  kernel rotates out of `updates` by allowing Fedora's signed `updates-archive`
  in the hardware transaction; `7.2.4-200.fc44` was resolved there.
- [x] Inspect tracked Fedora base references and callers; initial worktree clean.
- [x] Replace permanent Fedora base pins with floating defaults and one validated
  per-run CI reference shared by dependency builds and recorded in provenance.
- [x] Verify regression tests: `/usr/bin/python3 -m unittest discover -s tests -v`
  ran 225 tests, 204 passed, 21 opt-in skips, no failures. Workflow shell syntax
  tests, `bash -n scripts/build-nirius.sh` and `git diff --check` passed.
- [x] Validate the tag-tracking change with a real same-base dependency and
  complete image build.
- [ ] Perform booted hardware acceptance for the tag-tracking build.

Fedora is unsigned testing with Secure Boot disabled, using `testing` and dated
testing tags only. Hardware acceptance is separate from build validation and is
not a production signing/reviewer gate on test publication.

- [x] Hardware packages are implemented in Fedora source and a local expanded
  image built successfully; package integrity, exact-kernel ZFS pairing and
  runtime development-package exclusion checks passed. These additions are not published.
- [x] Consolidate essential usage, generic hardware caveats and safety boundaries
  into README; remove personal inventories and historical validation documents.
- [x] Verify concise documentation and local links; standard source suite:
  223 tests, 202 passed, 21 opt-in skips, no failures. No tests reference removed docs.
- [x] Remove historical personal documentation and anonymize maintainer commit
  metadata in the rewritten public main branch; verify the source tree is unchanged.
- [ ] Publish the hardware-expanded image through trusted `main` testing CI.
- [ ] Retest the published artifact with Secure Boot disabled: Wi-Fi, audio,
  cameras, readers, modems, graphics, suspend/resume, login and Noctalia lock.
  Package presence does not establish hardware recovery.
- [ ] Exercise current-artifact storage enrollment, independent recovery access,
  backup/restore including metadata and SELinux labels, and update/rollback.
- [ ] Cover independent-host SSH/network failures, storage/filesystem variants,
  wrong credentials, missing mounts, insufficient space, interruptions, reruns
  and long-duration retention using disposable storage.
- [ ] Verify rootless Compose, DevPod workspaces, Zed/Helix workflows, interactive
  Podman Desktop, virtualization and supported Fedora VFIO kernel arguments.
- [ ] Review inherited extlinux and `/var` tmpfiles lint warnings for ownership
  and boot impact; do not delete files blindly or claim warning-free validation.
