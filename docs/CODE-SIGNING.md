# Code signing and the "Windows protected your PC" warning

## Why the warning appears

**Microsoft Defender SmartScreen** shows *"Windows protected your PC"* when you run a
downloaded program that:

1. is **not digitally signed** with a code-signing certificate from a trusted
   authority, and
2. has not yet built up download **reputation** with Microsoft.

The BusinessPOS installer is currently unsigned, so Windows warns about every new
version. The warning is about who published the file, not about anything the
program does. Nothing inside the app can turn it off; only a signature can.

The warning applies **only to the downloaded installer**. Once BusinessPOS is
installed, opening it from the Start menu or desktop shortcut does not show it.

---

## Today, for free: install without the warning on your own PC

Use either method. Only do this for an installer you downloaded yourself from
this repository's Releases page; you can check its SHA-256 first, as described in
the README.

**Option A: unblock the file before running it** (no warning at all)

1. Right-click `BusinessPOS-Setup.exe` and choose **Properties**.
2. At the bottom of the *General* tab, tick **Unblock**, then click **OK**.
3. Run the installer normally.

Or in PowerShell:

```powershell
Unblock-File .\BusinessPOS-Setup.exe
```

**Option B: allow it once.** In the warning, click **More info → Run anyway**.

**Optional: ask Microsoft to review the file.** Submit the installer at
<https://www.microsoft.com/en-us/wdsi/filesubmission> as a *software developer*,
choosing "Incorrectly detected" and mentioning the SmartScreen warning. This is
free. It applies only to that exact file, so it has to be repeated for each new
version.

---

## Permanently: sign the releases

Signing proves the installer comes from you and hasn't been changed. The build is
already set up for it. Once the four secrets below exist, every **release** build
automatically signs:

- `BusinessPOS.exe`, the program
- `BusinessPOS-Setup.exe`, the installer
- the uninstaller

It then refuses to publish unless all three signatures are valid. Ordinary pushes
are never signed, which saves your signing quota.

### Which certificate

| Option | Available to an individual in India? | Notes |
|---|---|---|
| **OV code-signing certificate + SSL.com eSigner** (cloud signing) | **Yes** (individual validation with ID documents) | Supported by this repository's build. Roughly $129/year for the certificate plus an eSigner signing plan; check current prices. |
| EV code-signing certificate | Yes | Since 2024 EV **no longer** removes the warning instantly, so it isn't worth the extra cost here. |
| Azure Artifact Signing (formerly Trusted Signing), about $10/month | **No**: individuals must be in the USA or Canada | Cheapest option where eligible. |
| Self-signed certificate | — | Does **not** satisfy SmartScreen. |

**About reputation:** even with a valid signature, SmartScreen may still warn for
the first downloads of a brand-new certificate. The warning fades as people
download and run signed releases without problems, typically over days to a few
weeks. Every release signed with the same certificate builds on that reputation.

### Setting it up (SSL.com eSigner)

1. **Buy** an *OV Code Signing* certificate (Individual Validation) from SSL.com
   and complete identity verification.
2. **Enrol it in eSigner** (cloud signing) in your SSL.com account and set up
   two-factor authentication. Save the **TOTP secret** shown during setup; this
   is the text code behind the QR code.
3. In GitHub, open **Settings → Secrets and variables → Actions → New repository
   secret** and add:

   | Secret | Value |
   |---|---|
   | `ES_USERNAME` | your SSL.com account username |
   | `ES_PASSWORD` | your SSL.com account password |
   | `ES_TOTP_SECRET` | the eSigner TOTP secret from step 2 |
   | `ES_CREDENTIAL_ID` | optional; only needed if you have more than one certificate |

4. **Publish a release:** *Actions → Test & build installer → Run workflow* and
   tick **Publish a GitHub Release** (bump the version and changelog first).
5. **Check it:** the build log's *Verify signatures* step lists each file as
   `Valid` with your name. On Windows, right-click the downloaded installer →
   **Properties → Digital Signatures**, and your name appears there.

Avoid the `%` character in the eSigner password, because Windows batch files treat it
specially.

Secrets are encrypted by GitHub and are never shown in build logs, even on a
public repository. Builds from forks and pull requests cannot read them.

### Signing a local build

Set the same values as environment variables, and set `BPOS_CODESIGNTOOL_DIR` to
the folder containing SSL.com's `CodeSignTool.bat`. Then run
`build\build_installer.bat`. Without these variables the build is simply unsigned.
