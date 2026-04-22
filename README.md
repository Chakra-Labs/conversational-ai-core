# ⚡ Chakra Labs Conversational AI Platform (සිංහල)

LiveKit Agents මත ගොඩනගා ඇති, කාලීන (real-time) mult-modal වොයිස්/වීඩියෝ/පෙළ AI සංවාද පිටුවක් මෙහි ඇත. Chakra Labs Conversational AI Platform මගින් ඔබට ශීඝ්‍ර, අති විශාල concurrency, සහ පූර්ණයෙන්ම අභිරුචිගත AI chat අත්දැකීම් රූපවත් කරන්න පුළුවන්.

## සේවාව කෙටිවශයෙන්

- Instant text → live voice → video share in one session (එක් භාෂාවක හඬ/පෙළ, අවශ්‍ය නම් වීඩියෝ) 
- True low-latency, natural dialog tuned for Sinhala/Tamil/English
- Scales to දැඩි concurrent users — peak load-වලදීත් performance පහත බැසීමක් නැහැ
- APIs/SDKs සූදානම්: web, mobile, contact center, internal apps එකට පළිගන්වන්න එකවර

## මූලික අගය (Core Value Proposition)

- **Unmatched Scalability**: විශාල concurrent sessions සඳහා optimize. Peak demand-වලදීත් නිරවුල් latency.
- **Bespoke Customization**: ඔබේ domain එකට (e-commerce support, tutoring, internal knowledge bases, field ops) අදාළ ආකාරයෙන් වර්තමාන turn- එකේම tune කරගන්න.
- **Seamless Integration**: REST/WebSocket APIs, LiveKit Rooms හරහා වෙබ්/ජංගම/ඇතුළත පද්ධති වෙත few steps-වලින් සම්බන්ධ වන්න.

## ප්‍රධාන විශේෂාංග

- **Multi-Modal Interaction**: පාඨ, real-time voice (single language per session), වීඩියෝ / screen share යාවත්කාලීනව මාරු වීම.
- **Dynamic Response**: දත්ත/ඉලක්ක හඳුනාගෙන අර්ථවත්, කෙටි පිළිතුරු; අවශ්‍ය නම් tool calls හෝ API පියවර යෝජනා කරයි.
- **Context-Aware Personalization**: domain, audience, deployment surface අනුව tone/උදාහරණ වෙනස් කරයි.
- **Observability & Transcripts**: input/output transcripts log කර monitoring/QA සඳහා භාවිත කළ හැක.

## කේත පිහිටීම

- `src/agent.py`: LiveKit entrypoint, Gemini Live realtime model wiring, session management.
- `src/app/assistant.py`: Language-aware assistant wrapper.
- `src/app/instructions.json`: English/Sinhala/Tamil instruction bundles tuned for platform theme.
- `src/app/user_context.py`: Room metadata parsing (භාෂාව, use-case context) සඳහා.

## අවශ්‍යතා

- Python 3.9 හෝ ඉහළ
- LiveKit server/Cloud
- `.env.local` තුළ API යතුරු

## `.env.local` උදාහරණ

```
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
LIVEKIT_URL=
GOOGLE_API_KEY=
```

## සංවර්ධනය හා ධාවනය

1. අවශ්‍ය මොඩල් බාගත කිරීම:

```bash
uv run python src/agent.py download-files
```

2. Console පරීක්ෂණය (පෙළ/හඬ):

```bash
uv run python src/agent.py console
```

3. Dev mode (hot reload):

```bash
uv run python src/agent.py dev
```

4. නිෂ්පාදන ආරම්භය:

```bash
uv run python src/agent.py start
```

## කෙටි උදාහරණ සංවාදයක් (සිංහල)

පරිශීලකයා: "මගේ e-commerce chat එක ව්‍යාපාර peak වෙද්දි අඩු latency voice/video support එක් කරන්න ඕන."

Agent: "හරි! ඔබට භාවිතා කරන භාෂාව/voice mode එක මොකක්ද? වෙබ්/මොබයිල්/කොල් සෙන්ටර් 중 මොකක්ට deploy කරන්නද?"

පරිශීලකයා: "වෙබ් + සිංහල හඬ." 

Agent: "ඔයාට real-time Sinhala voice session single-language mode එකෙන් දෙන්නම්. SDK embed guide එක link කරලා දෙන්නද, නැත්නම් API step-by-step ද?"

## ආරක්ෂාව

- හානිකර/නීති විරෝධී ඉල්ලීම් ප්‍රතික්ෂේප කරයි.
- පුද්ගලික දත්ත ගැන නිර්මාණය/අනුමාන නොකෙරේ; අවශ්‍ය නම් පැහැදිලිව නොදන්නා බව පෙන්වයි.

අමතර උපකාර අවශ්‍ය නම් issue/PR එකක් විවෘත කරන්න — මම සිංහල/English දෙකම භාවිතා කරන්නම්.