# Character library / 人物库

Thirty original fictional personalities; twelve seats per game. Character identity
(name, portrait, habits) is separate from the secret game role. Choose someone,
or choose random; eleven other distinct characters are sampled. Saves retain
the exact cast. The original twelve-character saves remain supported.

三十位人物，每局十二人。人物不是狼人／预言家等秘密身份：外貌、背景与口头禅不提供身份线索。
角色设计借鉴职业气质与戏剧人物的反差，不是现实名人改名，也不宣称本人背书。

## Personality, not decoration

The expanded gallery is open by default. Each character now has a bilingual
voice audition, a motive/blind spot, and a specific reaction under pressure in
`character_playbooks.py`. These are supplied to model characters as acting
directions, not fabricated match events. They encourage different priorities,
humor, warmth, impatience and concessions rather than a mandatory analytical
template. A synthetic test can verify that these inputs arrive; it cannot prove
that every provider will enact them convincingly. Offline output remains bounded
by its structured response library. Public spectating is currently the offline
choice mode, not an unimplemented model-spectator claim.

人物选择区默认展开；三十人均有双语试读台词、动机与盲点、受压反应。
模型会收到这些表演指引，但试读台词不是对局事实，也不要求每轮重复口头禅。
真人可自由扮演所选人物，不强制照台词行动。模型表现仍需实际对局体验验证；
离线输出受选项库限制。公开旁观目前使用离线选项模式，不宣称已支持模型旁观。

Every profile has a strength, a blind spot and a speaking style. Six weights
(aggression, logic, bluff, loyalty, caution, verbosity) feed offline style and
model persona construction. Models receive the character description and voice;
offline NPCs still use structured choices rather than unrestricted language
understanding. These differences are implemented inputs, not proof of balanced
or reliably human-like behavior.

例如：林雀擅长组织叙事，也容易过早控制讨论；沈砚精于时序，却可能执着于小瑕疵；
赫雅能建立信任，却容易替动听的说法开脱；唐野愿意保护别人，也容易被挑衅；
苍默爱找反例，但会怀疑过头。没有“完美人格”或靠职业自动获得信息的特权。

完整双语档案来自：
- Original twelve: `werewolf_web/characters.py` and `offline_cast.py`.
- Additional eighteen: `werewolf_web/character_expansion.py`.
- Search and read all thirty in the web character gallery.

## New artwork / 新增肖像

Eighteen originals generated with the built-in OpenAI image generation tool at
the maintainer's request. No reference photographs or real-person likenesses
were supplied. The exact underlying image model version is not asserted.
Artwork licensing remains separate from the code; see [ASSETS](ASSETS.md).
The original PNGs and their provenance manifests are retained, without cropping,
resampling or metadata stripping.

Output path for each ID: `werewolf_web/static/img/portraits/<id>.png`.

Shared generation direction: one original fictional adult; distinctive and
charismatic rather than sexualized; illustrated visual-novel portrait,
anime-influenced hand-painted realism, warm amber lantern light and blurred
dark-plum night teahouse. Vertical waist-up composition, whole head visible,
recognizable face at thumbnail size. No text, watermark, logos, weapons, other
people or border. Subject-specific prompts:

- **linque**: Original adult East Asian stage director, cream suit, wine scarf, handwritten notes, charismatic composed expression.
- **shenyan**: Shen Yan, reserved male horologist age 45, East Asian, salt-and-pepper swept hair, round wire glasses, ink-blue vest, brass pocket watch, precise calm gaze
- **heya**: He Ya, female jazz singer age 32, Black African heritage, elegant natural coiled updo, emerald velvet jacket, gold small earrings, magnetic warm smile with discerning eyes
- **luobai**: Luo Bai, male mathematical illusionist age 29, light olive skin, wavy dark hair, charcoal rollneck, silver ring and one plain playing card in hand, mischievous beautiful grin
- **suming**: Su Ming, female field physician age 42, East Asian, shoulder-length dark hair with one silver streak, cream blouse and moss green coat, tired kind eyes and quiet authority
- **weilan**: Wei Lan, female long-distance sailor age 35, tan Mediterranean features, short wind-tousled chestnut hair, navy peacoat and faded red scarf, adventurous frank smile
- **jiyan**: Ji Yan, male cross-examiner age 50, East Asian, neatly combed silver-black hair, plum tailored three-piece suit, rectangular glasses, elegant piercing gaze, reserved expression
- **qiaoxi**: Qiao Xi, female street photographer age 27, East Asian, asymmetric black bob, mustard jacket, vintage camera at chest, lively candid smile
- **bailu**: Bai Lu, female chamber violinist age 31, pale freckles, long auburn hair loosely pinned, midnight-blue velvet dress with covered shoulders, composed melancholy beauty, violin bow resting beside her
- **tangye**: Tang Ye, male retired boxer and boxing coach age 48, broad dark-skinned face, bald head and trimmed beard, burgundy knitted cardigan, strong shoulders, tender unexpected smile, no bruises
- **moran**: Mo Ran, androgynous adult perfume archivist age 30, South Asian features, long black hair tied low, elegant indigo silk collar, tiny amber bottle, dreamy alert gaze
- **yunsu**: Yun Su, female auctioneer age 55, East Asian, immaculate silver pixie cut, ivory and cobalt tailored jacket, bold geometric brooch, commanding intelligent smile
- **luming**: Lu Ming, male radio astronomer age 33, East Asian, untidy black hair, thin glasses, warm brown corduroy jacket, small star notebook, gentle curious eyes
- **nanzhi**: Nan Zhi, female radio interviewer age 37, Middle Eastern features, dark wavy shoulder-length hair, warm rust blouse with high neckline, attentive welcoming expression, pen and interview notebook
- **guyan**: Gu Yan, male mountaineer age 40, tan East Asian, short cropped hair, subtle weathered face, forest-green wool overshirt, mountain-shaped small silver pin, steadfast direct gaze
- **xuning**: Xu Ning, female ceramic restorer age 46, East Asian, black hair loosely braided with silver strands, muted rose linen shirt, hands holding a tiny white ceramic bowl, serene knowing smile
- **cangmo**: Cang Mo, male chess columnist age 63, East Asian, silver hair and fine beard, dark plum traditional modern jacket, lively mischievous eyes, carved wooden chess piece held lightly
- **yuejian**: Yue Jian, female science-fiction playwright age 28, East Asian, shoulder-length violet-black hair, black jacket with cream shirt, asymmetrical silver earrings, luminous questioning eyes, confident half-smile
