# Product palette research — 2026-11-02

A small visual review of official public pages and published app screenshots. Marketing palettes and app UI palettes are recorded separately; these observations are not an industry-wide frequency estimate.

| Product | Official reference | Observed palette |
| --- | --- | --- |
| Wispr Flow | [App Store screenshots](https://apps.apple.com/us/app/wispr-flow-ai-voice-keyboard/id6497229487) | App screenshots show light gray/white input surfaces and black waveform/controls. Promotional screenshot backgrounds also use cream and black. |
| Wispr Flow | [Website](https://wisprflow.ai/) | Cream background, dark text, pale lilac primary buttons. A dark green announcement strip exists; it is not the whole page palette. |
| Superwhisper | [Official app/brand assets](https://superwhisper.com/assets) | Published app visuals include charcoal/black panels with white waveforms, plus light UI examples. |
| Superwhisper | [Website](https://superwhisper.com/) | Hero artwork uses dark blue/purple, with black/white controls. The hero is marketing artwork, not evidence that every app panel is purple. |
| Claude | [Product overview](https://claude.com/product/overview) | Warm off-white background, near-black text and actions, orange brand accent. This observation concerns the public product page. |
| Doubao | [Chat](https://www.doubao.com/chat/) | Redirected to a region-restriction page in this environment. The actual chat palette was not verified. |

## Decision for Voice Space

The useful pattern in these examples is a neutral reading surface with restrained brand or state accents, rather than a single required color for voice apps.

The product preview now uses our own palette:

- Canvas `#FAFAFA`, surfaces `#FFFFFF`, sidebar `#F4F4F5`.
- Main text and primary action `#242424`.
- Secondary text `#737373`, borders `#E5E5E5`.
- Voice/focus accent `#6559E8`, soft active fill `#F0EFFF`.
- Error text `#B54848`.

Olive/green-tinted surfaces, text, buttons, avatars and indicators have been removed from the product stylesheet. The functional lab remains the retained testing view. Accent color is concentrated in the voice graphic, active branch marker, focus ring and live state; the main action stays charcoal.

Desktop/mobile screenshots were reviewed using an isolated test workspace. Existing browser tests cover recording, playback confirmation, thought switching and restored content; this is a visual change and adds no model calls or voice behavior.
