# Current personality system

This is **random or fixed assignment of authored presets**, not procedural
generation of new personalities. When every slot is random, the eleven NPC
templates appear once each in a 12-seat match. Fixed selections can repeat a
preset. The human seat has no AI personality imposed on it.

## Preset inventory

These are template labels, not promises about a character's current display name.

| Template ID | Original label | Main authored tendency |
| --- | --- | --- |
| dashan | 大山 | Passionate, outspoken, instinct-led |
| amo | 阿墨 | Reflective and theatrical, prone to sudden intensity |
| alan | 阿岚 | Gentle, observant, understated |
| xiaoman | 小满 | Outwardly outgoing, sometimes hesitant |
| yexiao | 夜枭 | Earnest, socially motivated, nervous under pressure |
| xiaolu | 小鹿 | Playful, intuitive, changeable |
| aman | 阿蛮 | Analytical, confident, occasionally distracted |
| tiandou | 甜豆 | Cheerful, sociable, enjoys organizing the table |
| xicao | 细草 | Persistent questioning and demands for evidence |
| laomai | 老麦 | Patient, composed, seasoned table presence |
| aji | 阿吉 | Direct, challenging, disciplined but provocative |

The presets are loaded from `werewolf_web/data/personas/player-*.md`. They include
traits, speaking habits/catchphrases, role-playing habits and relationship prose.
The engine does not execute every sentence as a behavior rule.

## What actually affects play

- **Style:** aggression, logic, bluffing, loyalty, caution, verbosity, and an
  argument style (plain, logical, intuitive, two-sided or probing). Current values
  are extracted with hand-authored keyword rules from the canonical preset.
- **Cognitive profile:** evidence processing, recursive reasoning, social reading,
  deception, calibration, decisiveness and learning. Initial values are mostly
  derived from style, so personality and competence are not yet fully independent.
- **Temporary state:** match form, mood, arousal, confidence, stress and momentum.
  The match begins with bounded random variation; subsequent events can change
  state. This does not replace the base personality or continually redraw it.
- **Expression:** Chinese and English descriptions/catchphrases follow the assigned
  preset. Behavioral extraction uses the same canonical material in either locale.

These are game heuristics, not scientifically validated personality or cognitive
measurements. Distinct parameter values do not by themselves prove that players
will perceive convincingly distinct characters in long matches.

## How randomization works

1. Honor each fixed selection first. Random slots sample the remaining preset
   IDs without replacement. With all slots random, shuffle all eleven IDs: this
   default preserves the same preset mix in a different arrangement. A shuffle
   can retain an earlier pairing by chance. Duplicate fixed choices are allowed.
2. Independently shuffle the twelve localized display names without replacement.
   Custom names override selected entries; remaining random names avoid duplicates.
3. Seats and hidden game roles use the existing game random stream. Personality
   and name randomization use separate streams; renaming cannot reroll a role.
4. A supplied seed reproduces the name/preset assignment. Without a seed, new
   setup uses fresh randomness. Each NPC also has its own decision random stream.

For example, a display name that had the instinct-led preset can receive the
analytical preset in another match. Either can receive a wolf or a village role.
Changing a name does not change the assigned preset within the current match.

## What remains fixed or limited

- No generated personalities, dimension-by-dimension sampling or custom numeric
  personality editor in the ordinary game. Each NPC now supports a fixed preset
  or random-per-game selection; duplicate fixed presets are allowed.
- The name generator currently reshuffles a finite pool of twelve names per
  language; it does not invent new names. Users can enter their own before play.
- Names and presets remain fixed after the match starts. Temporary moods vary.
- Portraits still follow stable player IDs, not randomly assigned presets. The
  authored profiles retain some original character background/appearance cues;
  full portrait/background/personality coherence has not been rebuilt.
- Bounded cognitive growth and carry exist in code, keyed by trusted slot-plus-preset IDs
  within the adapter's memory scope. Web games get fresh session scopes, so this
  is **not yet a persistent cross-session character-progression feature**.
- The original conjecture shadow-day protocol has no personality inputs. The new
  [extreme full-game experiment](EXTREME_EXPERIMENT.md) has explicit frozen
  endpoint interventions, separate from the ordinary preset distribution.

See [name customization](CAST_CUSTOMIZATION.md) for the web/chat controls and
validation rules.
