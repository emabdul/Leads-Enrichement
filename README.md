# AppBird Game Exporter

A private Manifest V3 Chrome extension that exports game cards currently visible on an AppBird page. It runs locally in the Chrome session where you are already signed in.

## Install

1. Open `chrome://extensions` in Chrome.
2. Enable **Developer mode**.
3. Select **Load unpacked**.
4. Choose this `appbird-exporter` folder.
5. Open an AppBird game-results page and click the extension icon.
6. Select **Scan visible games**, then **Save new games to CSV**.

The CSV columns are `Release Date`, `Company LinkedIn`, `Game`, `Developer Name`, `Country`, `Email`, `Phone Number`, `Number of Games` - the order of the destination sheet, so a block of rows pastes straight in. Rows are sorted oldest first. Store URLs are direct App Store or Google Play URLs, not AppBird detail links. Locked cards are included when their App Store ID or Google Play package ID is present in the page.

The extension keeps a local record of previously saved store URLs. Future runs add only new games and update one cumulative file at `Downloads/AppBird Exports/appbird-games.csv`.

## Writing straight into a Google Sheet

Paste your sheet link into the popup once - it is remembered - then press
**Add new rows to Google Sheet**. The extension reads the sheet, skips every
game already listed there, and appends the rest under the last row, oldest
first. Matching is on game plus developer, ignoring case and punctuation.

It signs in as *you* through Chrome, so it can only touch sheets your own
account can already edit, and nothing is sent anywhere else.

### One-time setup

The extension id is pinned by the `key` field in the manifest, so it stays
`cpbhppfldhodkecbblcjnhfmmneacokh` wherever the folder lives.

1. **console.cloud.google.com** - create a project.
2. **APIs & Services > Library** - enable **Google Sheets API**.
3. **APIs & Services > OAuth consent screen** - choose *External*, fill in an
   app name and your email, and add your own Google account under
   **Test users**. Sign-in is refused without that last step.
4. **Credentials > Create credentials > OAuth client ID** - application type
   **Chrome Extension**, with the id above as the Item ID.
5. Copy the generated client id over `PASTE_YOUR_OAUTH_CLIENT_ID_HERE...`
   in `manifest.json`.
6. Reload the extension at `chrome://extensions`.

The first send opens a Google sign-in prompt; later ones reuse it.

## Country, Phone Number and Number of Games

`Country` and `Phone Number` are read from the same verified "About the developer" block as the
email, which carries four fields: legal name, email, postal address and phone. The country is
taken from the end of the address. **App Store rows are blank** for both - Apple publishes no
seller address.

`Number of Games` counts the developer's published apps: an artist lookup for the App Store
(exact), and a `pub:"name"` search for Play. Play caps public developer listings at 50, so a
developer at the ceiling reads `50+` rather than an understated number.

## Publisher contact columns

`Publisher Email` comes from the Google Play listing: the verified developer address in the
"About the developer" block, falling back to the public support address. **App Store rows are
blank** — Apple's lookup API publishes no contact address for a seller, only a support URL.

`Publisher LinkedIn` is a LinkedIn company *search* URL built from the publisher name, not a
resolved profile. LinkedIn has no public API and blocks automated lookups, so the link takes you
to the right search results and you pick the company yourself. Common legal suffixes
(Ltd, Inc, Oy, GmbH, Pte) are stripped to improve the match.

Both fields backfill into already-saved rows on the next scan.

## Scope

The extension does not send data anywhere. It reads only the game cards rendered in the current AppBird tab. Scroll the page first if you want additional lazy-loaded cards included before scanning. Its saved record is retained until you remove the extension or clear its site data in Chrome.
