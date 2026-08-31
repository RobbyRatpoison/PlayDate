# SteamGifts won-page fixtures

Synthetic, generic HTML for testing the SteamGifts wins parser (see
`project_steamgifts_wins_userscript` design). Structure mirrors real
`steamgifts.com` won pages (observed 2026-08) but every username, giveaway
code, appid, and key is invented.

**Never commit a real won-page dump here** — the private page embeds live
Steam keys and the account's username.

| File | Represents |
|------|------------|
| `won_public_page1.html` | `/user/<name>/giveaways/won` page 1 (25/page). 6 rows covering every variant + 2-page pagination nav. |
| `won_public_page2.html` | Same, last page. 3 rows, no "Next" link (short-page stop condition). |
| `won_private_page1.html` | `/giveaways/won` page 1 (50/page). Received / awaiting / not-received rows, each with the key column that the parser must never read. |

Row variants in `won_public_page1.html`:

1. `AAAA1` — normal app, feedback **received** (`giveaway__column--positive`)
2. `BBBB2` — `/sub/` package win, received
3. `CCCC3` — **awaiting feedback** (plain `<div>`, no class, no winner link) → pass-2 candidate
4. `DDDD4` — **not received** (`giveaway__column--negative`) *(markup is a best guess — confirm against a real not-received row)*
5. `EEEE5` — no-store gift card (heading href present, no `store.steampowered.com` icon link)
6. (no code) — invite-only, heading `href` and `giveaway__links` hrefs stripped (viewing as non-winner) → code unresolvable

`won_private_page1.html` per-row received icon (`.table__column--width-xsmall > i`):
green `fa-check-circle` = received (confirmed from real sample); `fa-question-circle`
(awaiting) and `fa-times-circle` (not received) are best guesses pending a real sample —
parser treats "not a green check" as the catch-all.
