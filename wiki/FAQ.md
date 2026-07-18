# FAQ

**Is this official / affiliated with PixAI?**
No. It's an unofficial personal-use tool that uses your own API key plus PixAI's
private frontend queries. PixAI's terms grant you copyright of your own generations.

**Will this get my account banned / does it steal credits?**
It's built to do the opposite of abuse: it only reads/manages *your own* account,
defaults to the **cheaper** generation priority, has no purchase automation, and is
rate-paced to be polite. It does claim PixAI's own free rewards (`--claims`/`--claim`,
daily credits + agent stamina) and auto-apply your free cards — self-service on your
own account, not farming. Generation spends your own credits: the CLI always asks
(`--confirm` is required to submit), while the web Generate drawer submits on click and
shows a live price estimate up front instead. For the full, precise list of what this
tool can and can't do to your account — plus a `READ_ONLY` config flag that refuses
every spend/delete path outright — see **[Trust & Safety](Trust-and-Safety)**.

**Do I really only need an API key?**
Yes. `USER_ID` auto-resolves from the key and the persisted-query hashes ship as
defaults. See [Setup](Setup) and [How It Works](How-It-Works).

**Why are there "hashes" if I don't need to set them?**
They're public identifiers of PixAI's own frontend queries (not secrets), baked in so
you don't capture anything. You only touch one if PixAI overhauls their frontend —
[Troubleshooting](Troubleshooting) covers recapture.

**Where do my files and credentials go?**
Everything is local. `config.json`, `token.txt`, and `pixai_backup/` are git-ignored.
Nothing phones home.

**Can I run it on my phone/tablet?**
Yes — launch the gallery with `--host 0.0.0.0 --https` and open it on your device
(installable as a PWA). [Select mode](Collections) is touch-friendly. A LAN-exposed
gallery is **read-only** — every credit-spending and destructive endpoint is gated to
localhost, so LAN browsers can look but only the owner's machine can spend or delete.
Still use a trusted network: LAN viewers can see your images and prompts.

**Does organizing files break the gallery?**
No. Lookups are by `media_id`, so files can live in any subfolder.
[Collections](Collections) are catalog-based and survive Organize too.

**How do I update?**
`git pull`. If using the GUI, **fully quit and reopen it** (Stop/Launch doesn't
reload the code) — see [Troubleshooting](Troubleshooting).

**Something broke after a PixAI change.**
See [Troubleshooting](Troubleshooting) — usually a one-line hash recapture.
