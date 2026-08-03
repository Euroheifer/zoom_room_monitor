# ZDM Enrollment Troubleshooting Q&A — Zoom Rooms (Windows/Mac) & iPad Controllers

**Audience:** IT support / helpdesk
**Scope:** Common issues when enrolling Zoom Rooms computers (Windows and macOS) and iPads (Zoom Rooms Controllers / Scheduling Displays) into Zoom Device Management (ZDM), and how to resolve them.
**How to use this page:** Find the platform section for the device in the ticket, match the symptom, follow the numbered fix. Every entry ends with a fallback if the fix doesn't work.

**Question index**

| # | Platform | Question |
|---|---|---|
| Q1 | Any | Activation code rejected / expired / "wrong account or site" error |
| Q2 | Windows | 802.1X auto-enabled after ZDM enrollment, device drops off the network |
| Q3 | Windows | Enrolled in ZDM but not assigned to its Zoom Room |
| Q4 | Windows | Device doesn't appear in the ZDM console after enrollment |
| Q5 | macOS | Camera/mic/screen share broken after enrollment or macOS update |
| Q6 | macOS | Mac room shows offline — especially after every reboot |
| Q7 | macOS | Remote commands (upgrade/restart) greyed out or never execute |
| Q8 | iPad | Zoom Rooms app never pushed/installed after enrollment |
| Q9 | iPad | iPad missing from ZDM device list / room-assignment dropdown |
| Q10 | iPad | Controller can't pair or sign in to its room |
| Q11 | iPad | All ZDM iPads stopped responding at once (APNs certificate) |

---

## Before you start: enrollment prerequisites

Most enrollment tickets trace back to one of these. Check them first.

**Network / firewall**
- Allowlist `https://zdmapi.zoom.us` and `https://zdm.zoom.us` (ZDM endpoints), plus Zoom's standard domains `*.zoom.us` / `*.zoom.com`. Full official list: [Zoom network firewall or proxy server settings](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0060548) and [Firewall configuration for Zoom Rooms](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0065712).
- Key ports: TCP 443 outbound; UDP 3478, 3479, 8801 (media); TCP 9090/9091 between controller and room PC on the LAN.
- Exempt `zoom.us` and `*.zoom.us` from SSL inspection — Zoom's official recommendation.
- Windows MDM enrollment **fails behind authenticating proxies** ([Microsoft known issue](https://learn.microsoft.com/en-us/windows/client-management/mdm-known-issues)).
- iPads additionally need Apple APNs reachable: TCP 5223 (fallback 443) to `*.push.apple.com` (Apple's 17.0.0.0/8 range), plus App Store/CDN access.
- Wi-Fi for controllers: disable AP/client isolation, and keep controller and room PC on the same subnet/VLAN (or routed with 9090/9091 open).

**Activation codes**
- Generated when the room is created: web portal → **Room Management → Zoom Rooms** → Activation Code column (also emailed to the account owner).
- **Valid for 10 days**, room-specific. Expired → regenerate from the same page.
- The activation code signs a device into a *room*; **ZDM enrollment is a separate step** (access code / QR / provisioning package / Apple Business Manager).

**Platform requirements**
| Platform | Requirement |
|---|---|
| Windows | Windows 10/11 **Pro, Enterprise, or Education** (Home cannot do MDM enrollment); version 1703+ for manual enrollment and auto sign-in |
| macOS | Zoom Rooms app at global minimum version+; **Apple MDM Push (APNs) certificate** uploaded in the Zoom portal; enroll via **Safari** at `zdm.zoom.us`; ABM/ASM for automated enrollment |
| iPad | Must be **supervised** (Apple Business Manager, or Apple Configurator for manual enrollment); APNs certificate uploaded; disable auto OS/App Store updates, Auto-Lock = Never |

**Account/license:** Zoom Rooms license, and account owner/admin (or Zoom Rooms role) privileges to manage ZDM.

---

## Any platform

### Q1. The activation code is rejected, expired, or gives "Zoom Rooms can't verify the connection. You may have used the wrong account/site to sign in."

**Symptom:** Entering the 16-digit activation code on the room device or controller fails.

**Likely causes:** Code older than 10 days; room created under a different Zoom account/sub-account or site than the one the device is signing into; firewall blocking Zoom Rooms ports; stale config on the device.

**Fix:**
1. Regenerate the code: web portal → **Room Management → Zoom Rooms** → the room → Activation Code → regenerate. Enter it promptly (10-day validity).
2. Confirm the room exists in the *same* Zoom account/site the device is signing into — check with the admin who created the room.
3. Verify network: TCP 443 + UDP 3478/3479 outbound and Zoom's domain allowlist. Test on a hotspot to isolate the firewall.
4. Quit and relaunch the Zoom Rooms app, then retry.

**If that doesn't work:** Sign in with account owner/admin credentials instead of a code and pick the room from the list. Last resort: delete and recreate the room in the portal and use the new code.

*Sources: [Signing in to Zoom Rooms (KB0064185)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0064185), [Zoom Community — activation error thread](https://community.zoom.com/t5/Rooms-and-Workspaces/Error-message-from-Zoom-Room-when-trying-to-enter-activation/td-p/65245)*

---

## Windows (Zoom Rooms)

### Q2. After enrolling in ZDM, the Windows device auto-enables 802.1X and drops off the network

**Symptom:** Post-enrollment, the NIC's Authentication tab is active (Wired AutoConfig / `dot3svc` service running), the adapter attempts IEEE 802.1X authentication, and on switch ports without 802.1X the machine loses network and the room goes offline.

**Likely causes:**
- A **ZDM network profile** assigned to the device. ZDM Ethernet ("Any Ethernet") profiles are a Windows-only feature that pushes enterprise 802.1X settings (EAP-TLS or PEAP with directory credentials); applying one forces Windows to enable Wired AutoConfig.
- A **domain Group Policy**. On domain-joined machines, a **Wired Network (IEEE 802.3) Policy** in Active Directory enables Wired AutoConfig / 802.1X on the NIC — check this whenever no ZDM profile is assigned.
- Either way, on a LAN with no 802.1X authenticator the adapter fails authentication and loses connectivity.

> ⚠️ Our team has confirmed cases where 802.1X was enabled after enrollment with **no ZDM network profile assigned**, and there is no Zoom documentation that bare enrollment does this by itself. In practice: check the ZDM profile and AD Group Policy, and if neither shows anything special, simply turning 802.1X off on the NIC fixes it.

**Fix:**
1. In the web portal: **Device Management → System Config → Network tab** — check whether any Ethernet network profile is assigned to the affected device. If your LAN doesn't use 802.1X, unassign it (ellipsis "…" menu on the profile → device assignment) or delete the profile.
2. Check the Active Directory Group Policy applied to the computer: **Computer Configuration → Windows Settings → Security Settings → Wired Network (IEEE 802.3) Policies** (on the device, run `rsop.msc` or `gpresult /h report.html` to see what actually applied). If a wired policy exists, exclude the Zoom Rooms machines from its scope.
3. If neither shows anything special, **just turn 802.1X off on the NIC** — confirmed fix in our environment:
   - NIC Properties → **Authentication** tab → uncheck "Enable IEEE 802.1X authentication".
   - Optionally stop the service too: `services.msc` → **Wired AutoConfig (dot3svc)** → Stop, set Startup type back to **Manual** (the Windows default). Or CLI: `netsh lan show profiles`, then `netsh lan delete profile interface="Ethernet"`; `sc config dot3svc start= demand` and `sc stop dot3svc`.
4. Reboot (or replug the NIC) and confirm the device shows online again in **Device Management → Device List**.
5. Prevent recurrence: only apply 802.1X wired policies (ZDM profile or GPO) to devices on switch ports that actually run 802.1X.

![Windows NIC Ethernet Properties, Authentication tab, with the Enable IEEE 802.1X authentication checkbox](https://help.ku.edu.tr/__attachments/a_799ffad3df4365bba3e99dae3d4b4dfa696b52c2d644c489fe4c2d6e82ccc993/ethernetproperties.jpg)

*Where to turn 802.1X off: NIC Properties → Authentication tab. Shown here with 802.1X enabled — **uncheck** the top box to disable it. (Screenshot: Koç University IT KB)*

![Wired AutoConfig service listed in services.msc](https://help.ku.edu.tr/__attachments/a_aae9edbca90cc7a318a5fa9646d027c6454f4664841c74c3271cef607f7a69c5/wiredautoconfig..png)

*The Wired AutoConfig (dot3svc) service in services.msc. (Screenshot: Koç University IT KB)*

**If that doesn't work:** Unenroll the device (**Settings → Accounts → Access work or school → Disconnect**), fix the NIC as above, re-enroll, and open a Zoom ticket with logs — the trigger isn't publicly documented.

*Sources: [Configuring ZDM network profile (KB0065385)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0065385), [Getting started with ZDM (KB0060137)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0060137), [Windows ZDM FAQ (KB0067490)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0067490)*

### Q3. Windows device enrolled in ZDM but is not assigned to its Zoom Room

**Symptom:** The device appears in **Device Management → Device List** and checks in, but the intended room shows no device; the Zoom Rooms app sits at the sign-in screen.

**Likely causes:** ZDM enrollment and room association are **two separate steps** — nothing assigns an enrolled device to a room until an admin does it (or the device signs in with an activation code). Auto sign-in also has prerequisites: the device must be MDM-enrolled **and** on Windows 10 1703+, otherwise the portal shows "**Cannot be assigned**". Devices enrolled via the legacy 1607 flow don't even appear in the portal until after their first room login. A mistyped serial in "Assign unlisted device" also leaves the room empty.

**Fix:**
1. Web portal → **Room Management → Zoom Rooms** → **Edit** next to the target room.
2. Under **Auto sign in room**, click **Assign Device**, pick the enrolled device and device type, **Save**. The Zoom Rooms app then installs and signs in automatically.
3. If the device isn't in the dropdown: **Assign unlisted device** → enter the machine's serial number (double-check it on the device).
4. Zoom's best practice: do assignment from the **Devices tab** (Room Management → Zoom Rooms → Devices) and rename the machine to match the room name first, so serials are findable.
5. If you see "Cannot be assigned": confirm Windows 10 1703+ and that **Settings → Accounts → Access work or school** shows "Connected to Zoom Rooms MDM".
6. Assigned to the wrong room? **Device Management → Device list → "…" → Remove from Zoom**, then re-assign.

![Zoom web portal device list, Devices tab, with platform, managed-device, and status filters](https://1175968039-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces%2FctBXUMeBy4rtLMmMkKRG%2Fuploads%2FcZ8oQTyvdhgRyECu3UYx%2Fimage.png?alt=media&token=cab52f31-5d26-4806-9f6f-1434239a791c)

*The Devices tab in the Zoom web portal — where enrolled devices appear and where Zoom recommends doing room assignment. (Screenshot: Zoom Technical Library)*

**If that doesn't work:** Sign the room in manually with its activation code (regenerate if older than 10 days) or admin credentials.

*Sources: [Enabling auto sign-in with ZDM (KB0068603)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0068603), [Best Practices for ZDM Mac/Win (KB0066429)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0066429), [Using ZDM with Windows devices (KB0061369)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0061369)*

### Q4. Windows device doesn't appear in the ZDM console after enrollment

**Symptom:** Enrollment (access code, token, or `zdm.ppkg`) appears to complete on the device, but nothing shows in Device Management. Client logs may show `ZDMServiceMgr error code 5002`.

**Likely causes:**
- **Client version bug:** Zoom client 6.1.1 had a confirmed bug (error 5002 — enrollment token tried to register against a China enrollment server). Fixed in 6.1.5+ / 6.1.10.
- MDM enrollment never actually completed (no "Connected to Zoom Rooms MDM" entry in Settings).
- Legacy Windows 1607 enrollment: those devices only appear in the portal **after the first Zoom Room login**.
- Firewall/proxy blocking `zdmapi.zoom.us` / `zdm.zoom.us`, or an authenticating proxy (breaks Windows MDM enrollment).
- Unsupported edition: Windows Home cannot enroll.

**Fix:**
1. Update the Zoom Rooms / Zoom Workspace client to current (at minimum past 6.1.1) and retry.
2. On the device: **Settings → Accounts → Access work or school** must show **Connected to Zoom Rooms MDM**. If not, re-run the enrollment link or ppkg.
3. Confirm Windows Pro/Enterprise/Education, version 1703+.
4. Verify `zdmapi.zoom.us`, `zdm.zoom.us`, and `hybridupdate.zoom.us` (ppkg host) are allowlisted; bypass any authenticating proxy for this machine.
5. If enrolled via the 1607 flow: sign the Zoom Rooms app into a room first, then re-check the portal.

**If that doesn't work:** Disconnect the Zoom Rooms MDM entry, reboot, re-enroll with a current client. Still failing → collect client logs (note the 5002 line) and open a Zoom ticket.

*Sources: [Zoom Community — ZDM Enrollment Error 5002 (solved)](https://community.zoom.com/t5/Zoom-Rooms-and-Workspaces/ZDM-Enrollment-Issue-Error-5002/m-p/195567), [Using ZDM with Windows devices (KB0061369)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0061369), [Microsoft — MDM known issues](https://learn.microsoft.com/en-us/windows/client-management/mdm-known-issues)*

---

## macOS (Zoom Rooms)

### Q5. Mac enrolled and the app runs, but camera/mic/screen share are broken (or a permission dialog is stuck on screen)

**Symptom:** Room signs in but has no video/audio or screen share fails; after a macOS update, a permission dialog sits on the screen of a headless Mac nobody can click. On macOS 15 Sequoia, screen sharing re-breaks **monthly**.

**Likely causes:** macOS TCC privacy consent — Camera, Microphone, Screen Recording, and Accessibility must be approved per app, and ZDM enrollment does **not** grant them. Zoom Rooms runs unattended, so prompts go unanswered. Sequoia additionally re-prompts screen-capture apps every month unless suppressed via MDM.

**Fix:**
1. On the Mac (attach keyboard/mouse or use screen sharing): **System Settings → Privacy & Security** → enable **Zoom Rooms** under Camera, Microphone, Screen & System Audio Recording, Accessibility, and Full Disk Access. Relaunch Zoom Rooms.
2. When upgrading macOS on a room Mac, keep keyboard/mouse connected until Zoom Rooms has been opened and all prompts approved (Zoom's documented guidance).
3. To pre-approve at scale, push a PPPC privacy profile from your MDM using Zoom's published values — bundle ID `us.zoom.ZoomPresence`, code requirement `identifier 'us.zoom.ZoomPresence' and anchor apple generic`, with Full Disk Access = Allow and Accessibility = Allow (needed to dismiss the screensaver). Zoom provides a .plist template.
4. On macOS 15: deploy an MDM profile to suppress the monthly screen-capture re-authorization — it cannot be disabled locally.

![macOS Security and Privacy settings, Privacy tab, Camera section with Zoom Rooms allowed](https://assets.zoom.us/images/en-us/zoom-rooms/mac/mac-permissions-camera-zr.png)

*macOS Security & Privacy → Privacy → Camera with Zoom Rooms allowed — repeat for Microphone, Screen Recording, Accessibility, and Full Disk Access. (Screenshot: Zoom official asset)*

**If that doesn't work:** Toggle the permissions off/on and reboot. Plan a physical visit with keyboard/mouse once per macOS major upgrade if you can't push PPPC profiles.

*Sources: [Using MDM for Zoom Rooms with macOS (KB0069009)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0069009), [9to5Mac — Sequoia monthly screen-recording prompt](https://9to5mac.com/2024/08/14/macos-sequoia-screen-recording-prompt-monthly/)*

### Q6. Mac room shows offline in the console — especially after every reboot

**Symptom:** Room or device shows offline even though the Mac is powered on. Classic pattern: the Mac reboots overnight and the room stays down until someone logs in on the Mac. Sometimes the *room* shows offline while the *device* tab shows online.

**Likely causes:** **Auto-login not enabled** on the macOS account, so after reboot the Mac sits at the login window and Zoom Rooms never launches (Zoom's remote-restart features explicitly require auto-login; FileVault must be off). Other causes: blocked ports/DNS, an expired Apple MDM push certificate (annual expiry — devices offline past expiry must be re-enrolled), or a known console bug displaying mismatched room/device status.

**Fix:**
1. Verify real status first: **Device Management → Device List** — the device should carry the **ZDM badge** (= communicating with ZDM). If the Rooms page and Devices tab disagree, test the room in a live meeting before chasing a phantom outage.
2. Enable auto-login: System Settings → Users & Groups → automatically log in as the Zoom Rooms user (requires FileVault off), and set Zoom Rooms to launch at login.
3. Use Zoom's **Weekly system restart** (Room Management → Zoom Rooms → Account Settings → Meetings tab) instead of a bare OS-level reboot schedule.
4. Check network reachability (TCP 443, UDP 3478/3479 + domain allowlist) and DNS from the Mac.
5. Check the APNs certificate expiry in the ZDM portal; renew **with the same Apple ID** before it lapses.
6. Device stopped communicating entirely? Remove it from ZDM (**Device List → "…" → Remove Device**), re-enroll via Safari + access code, re-assign to the room from the Devices tab.

**If that doesn't work:** Sign the room in manually once (activation code or admin credentials), confirm auto-login/launch items, and if it recurs open a Zoom ticket with the device serial and a problem report.

*Sources: [Remote Zoom Rooms Management (KB0068519)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0068519), [Weekly system restart (KB0067561)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0067561), [Best Practices for ZDM Mac/Win (KB0066429)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0066429)*

### Q7. Remote commands (upgrade app, restart app/computer) are greyed out or never execute on the Mac

**Symptom:** The Upgrade button doesn't appear even though the Mac's app is outdated; restart commands are unavailable or do nothing.

**Likely causes:** The device isn't actually communicating with ZDM (no ZDM badge — the portal won't offer Upgrade); the Mac was **manually enrolled** (Zoom: manually enrolled Macs can't be upgraded through the portal); auto-login isn't enabled (a restart prerequisite); the room is offline; or the app/controller is below the minimum version for remote management.

**Fix:**
1. Confirm the **ZDM badge** in Device Management → Device List. No badge → fix enrollment/communication first (see Q6 step 6).
2. Upgrade path: **Device Management → Device List → Devices tab → "…" next to the Mac → Upgrade**.
3. Restart path: **Room Management → Zoom Rooms → select an online room → Edit → Devices section → Restart Zoom Rooms App / Restart Zoom Rooms Computer**.
4. Ensure auto-login is on and app + controller meet the minimum versions in Zoom's remote-management article.
5. Still stuck: remove from ZDM, re-enroll (ideally via ABM, not manual), re-assign, retry.

**If that doesn't work:** Use the web-based room controller (Room Management → Zoom Rooms → select the room) for in-room actions, your corporate MDM/remote tool for the update, or an on-site restart.

*Sources: [Managing ZR devices from device management (KB0058060)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0058060), [Remote Zoom Rooms Management (KB0068519)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0068519), [Remotely upgrading ZR devices with ZDM (KB0063224)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0063224)*

---

## iOS / iPadOS (Controllers & Scheduling Displays)

### Q8. iPad enrolled in ZDM, but the Zoom Rooms app was never pushed/installed

**Symptom:** The iPad shows as managed (Settings → General → Profiles & Device Management shows "Zoom Rooms MDM", or Remote Management was accepted during setup), but the Zoom Rooms Controller app never appears on the home screen.

**Likely causes:** The install command is delivered over Apple APNs and the app binary comes from the App Store — if either is blocked on the network, the profile installs but the app never arrives. Other causes: expired Apple MDM push certificate (see Q11), a half-completed manual (QR) enrollment, the device not truly supervised, or a stuck MDM command queue (an offline/asleep iPad processes commands only on its next check-in — a reboot forces one).

**Fix:**
1. Confirm enrollment completed: **Device Management → Device List** — the iPad should show the **ZDM badge**.
2. Give it a few minutes (Zoom says the app auto-downloads "within minutes"), then **reboot the iPad** — this forces an APNs check-in and reprocesses pending commands.
3. **Manual/QR enrollments — Zoom's official retry:** on the iPad, **Settings → General → Profiles & Device Management → Zoom Rooms MDM → Remove Management**, then re-scan the QR code / re-enter the access code from Device Management → Enrollment. This re-triggers the app download.
4. **ABM enrollments:** verify the serial is assigned to the *Zoom* MDM server in Apple Business Manager, click **Refresh** on the ZDM Enrollment page, then factory reset (Erase All Content and Settings) and re-run Setup Assistant.
5. Verify the network allows `zdmapi.zoom.us`, APNs (TCP 5223/443 to `*.push.apple.com`), and App Store domains on the controller VLAN. Test on a hotspot to isolate.
6. Check the Apple MDM push certificate at **zoom.us/mdm/certificate/management** is present and unexpired.

**If that doesn't work:** Install the "Zoom Rooms" app manually from the App Store and sign in with the room's activation/pairing code — the iPad stays ZDM-enrolled for future management. (This is exactly how a Zoom Community ZDM-migration case was resolved.) If even that fails: remove management, factory reset, re-enroll, and open a Zoom ticket with the serial.

*Sources: [iPad ZDM FAQ (KB0067239)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0067239), [Using ZDM with iPads (KB0066078)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0066078), [Best Practices for ZDM iPads (KB0066931)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0066931), [Zoom Community — ZDM issues for iPad Minis](https://community.zoom.com/t5/Rooms-and-Workspaces/ZDM-Issues-for-iPad-Minis/td-p/144002)*

### Q9. iPad doesn't appear in the ZDM device list, or can't be selected when assigning a room

**Symptom:** No ZDM badge in Device Management, or the iPad is missing from the "Assign Device" dropdown when editing a room.

**Likely causes:** ABM assignments not synced into Zoom (the Enrollment page needs a manual **Refresh**); the iPad was assigned in ABM *after* it was already set up (Automated Device Enrollment only applies during Setup Assistant → needs a factory reset); the iPad wasn't bought through Apple/an authorized reseller tied to your ABM (can only be added via Apple Configurator); or it's already assigned to another room.

**Fix:**
1. In ABM: **Devices** → confirm the serial is assigned to the **Zoom MDM server** (not the corporate MDM).
2. Zoom portal → **Device Management → Enrollment (Apple tab)** → **Refresh**.
3. Factory reset the iPad and complete Setup Assistant, accepting the **Remote Management** prompt.
4. Missing from the room-assignment dropdown? Use **Assign unlisted device** and enter the serial manually — Zoom's official workaround — and check it isn't already assigned to another room.
5. Used/non-ABM iPads: add to ABM via Apple Configurator, or use manual QR enrollment (supervise the iPad with Configurator first).

**If that doesn't work:** Enroll manually via QR instead of ABM. (Careful: fully *releasing* a device from ABM may prevent re-adding it.) Escalate to Zoom with the serial.

*Sources: [Best Practices for ZDM iPads (KB0066931)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0066931), [iPad ZDM FAQ (KB0067239)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0067239)*

### Q10. iPad enrolled and app installed, but the controller can't pair or sign in to its room

**Symptom:** The controller app opens but can't find the room, the pairing code errors, or a ZDM-assigned iPad never signs into its room. Sometimes no pairing code is offered at all (only a sharing code).

**Likely causes:** Network segmentation — the iPad and room computer must reach each other on **TCP 9090/9091** (same subnet/VLAN or routed; AP/client isolation breaks this). Auto sign-in prerequisites unmet (supervised + MDM-enrolled + assigned under the room's "Auto sign in room"). The room is already signed in on another controller (pairing code replaced by a sharing code). Or the device is assigned to the wrong room.

**Fix:**
1. Confirm iPad and room PC are on the same network segment with TCP 9090/9091 permitted; toggle the iPad's Wi-Fi and reboot the access point (this alone resolved one community case).
2. Portal → **Room Management → Zoom Rooms → Edit (room) → Auto sign in room → Assign Device** (or Assign unlisted device + serial). Save, relaunch the controller app.
3. Verify the ZDM badge and that the iPad isn't assigned to a different room.
4. Pairing manually? Sign the room out of any existing controller session so a fresh pairing code is generated.
5. Reboot the iPad.

**If that doesn't work:** Sign in on the controller with the room's activation code directly. If certificates are suspected (previously unmanaged iPads have hit invalid-device-certificate states), remove and re-enroll the device in ZDM. Persisting → Zoom ticket.

*Sources: [Enabling auto sign-in with ZDM (KB0068603)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0068603), [Firewall configuration for Zoom Rooms (KB0065712)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0065712), [Zoom Community — controller won't pair](https://community.zoom.com/t5/Zoom-Rooms-and-Workspaces/Zoom-Rooms-Controller-Won-t-Pair/td-p/63860)*

### Q11. All ZDM iPads stopped responding to commands at once / new enrollments fail

**Symptom:** Every ZDM iPad simultaneously stops receiving upgrades and commands; new enrollments fail.

**Likely causes:** The **Apple MDM Push (APNs) certificate expired**. It's valid for one year. Renewed with the same Apple ID → management resumes without re-enrollment. Replaced with a *new* certificate (different Apple ID or "Create" instead of "Renew") → **every device must be re-enrolled**.

**Fix:**
1. Check expiry at **zoom.us/mdm/certificate/management** (Zoom portal, Device Management certificate page).
2. To renew: download a fresh CSR from Zoom → sign in at [identity.apple.com](https://identity.apple.com) **with the same Apple ID used originally** → click **Renew** on the existing certificate (never "Create") → upload the renewed certificate back to Zoom.
3. Record the certificate's Apple ID in the team runbook and use a role account, not a personal one. Apple emails expiry warnings at 30/10/1 days.

**If that doesn't work (certificate was replaced, not renewed):** Re-enroll all devices — factory reset ABM units and re-run Setup Assistant; manual units remove the profile and re-scan the QR code. Open a Zoom ticket if the portal won't accept the renewed certificate.

*Sources: [Using ZDM with iPads (KB0066078)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0066078), [Best Practices for ZDM iPads (KB0066931)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0066931), [Addigy — push certificate expired FAQ](https://support.addigy.com/hc/en-us/articles/8360182820243-FAQ-My-Push-Certificate-Expired)*

---

## Escalation: before you contact Zoom Support

Zoom Rooms logs are **encrypted and only readable by Zoom Support**, so the flow is ticket-first:

1. **Collect the basics:** room name, device platform + Zoom Rooms app version, OS version, serial number (Device Management → Device list → Devices tab), enrollment method used, exact error text/code (e.g., 5002), and the failure timestamp **with timezone** — timestamps are how Zoom maps your report to the logs.
2. **Open the ticket first:** [support.zoom.com → Submit a Request](https://support.zoom.com/hc/en/new-request?id=new_request&sys_id=cb06ab4b8702255089a37408dabb3555) — Request Type: Technical Support, Product: Zoom Rooms, set Priority (reserve high for room-down). Note the ticket number from the confirmation email.
3. **Then send logs from the controller:** Settings → **About → Help → Send Problem Report** (in-meeting: More → Settings → About → Help). Include the ticket number in the report description. For audio issues, enable the **Audio Log** toggle during the meeting first.
4. Phone support is only available on Business/Enterprise/Education plans; web ticket + chat for all licensed accounts.

*Sources: [Troubleshooting logs for Zoom Rooms (KB0061640)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0061640), [Zoom support plans](https://www.zoom.com/en/support-plans/)*

---

## Reference: key Zoom KB articles

| Topic | Article |
|---|---|
| Getting started with ZDM | [KB0060137](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0060137) |
| ZDM for Windows | [KB0061369](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0061369) |
| ZDM for Mac | [KB0062257](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0062257) |
| ZDM for iPads | [KB0066078](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0066078) + [FAQ KB0067239](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0067239) |
| ZDM best practices (Mac/Win) | [KB0066429](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0066429) |
| ZDM best practices (iPads) | [KB0066931](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0066931) |
| Auto sign-in with ZDM | [KB0068603](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0068603) |
| Network profiles (802.1X) | [KB0065385](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0065385) |
| Firewall for Zoom Rooms | [KB0065712](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0065712) |
| Signing in / activation codes | [KB0064185](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0064185) |
| Troubleshooting logs | [KB0061640](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0061640) |
