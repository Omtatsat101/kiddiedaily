"""
KiddieDaily Agentic News Scraper v1.0
Fetches RSS from curated bias-rated sources → scores bias + source agreement → generates kid-friendly
HTML articles → pushes to Omtatsat101/kiddiedaily GitHub Pages.

Local run:  python scrape_and_push.py
GitHub Actions: triggered daily at 10am UTC via .github/workflows/daily-news.yml (self-deployed)

Requires:  GITHUB_TOKEN  (env var or projects/API-KEYS.env)
Optional:  ANTHROPIC_API_KEY  (for Claude Haiku kid-friendly rewrites)
"""
import urllib.request, urllib.error, urllib.parse, ssl, json, base64, time, os, pathlib, re, sys, unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# Force UTF-8 on Windows so emoji in print() don't crash
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── SSL (matches existing kiddiedaily scripts) ────────────────────────────────
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# ── Auth ──────────────────────────────────────────────────────────────────────
def _load_token(env_var, prefix):
    val = os.environ.get(env_var)
    if val:
        return val.strip()
    p = pathlib.Path(__file__).resolve().parents[1] / "API-KEYS.env"
    if p.exists():
        for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if ln.startswith(prefix):
                return ln.split("=", 1)[1].strip().strip('"')
    return None

GITHUB_TOKEN = _load_token("GITHUB_TOKEN", "GITHUB_TOKEN=")
ANTHROPIC_KEY = _load_token("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY=")
REPO = "Omtatsat101/kiddiedaily"
MAX_ARTICLES          = 15  # max new articles per run (11 sci + 4 world)
MAX_SCI_PER_RUN       = 11  # max science articles per run
MAX_WORLD_PER_RUN     = 4   # max world-news articles per run
MAX_PER_SOURCE_PER_RUN= 3   # max articles from any single source per run (prevents domination)
MAX_SPORTS_TOURNAMENT_PER_RUN = 1   # cap for any single major live tournament (World Cup, Wimbledon, Olympics…)

# Regex word-boundary filter — avoids substring false positives like "scraper"→"rape"
_ADULT_TITLE_RE = re.compile(
    r'\b(?:'
    r'vagina|penis|vulva|genitals?|testicle|erectile|sperm(?!\s+whales?)|semen|ovary|uterus|cervix'
    r'|sexual(?:\s+(?:assault|abuse|violence|misconduct|offen[cs]e|predator|exploitation|harassment))?|sexuall?y|rap(?:e|es|ed|ing|ist)|molest\w*|(?:paedo|pedo)phil\w*|drugging'
    r'|abortion|contraception|condom'
    r'|nude|naked(?!\s+mole)|pornograph'
    r'|genocide|massacre|beheading|torture'
    r'|suicide|overdose|opioid\s+overdose|drug\s+addict'
    r'|cocaine|heroin|fentanyl|methamphetamine|crystal\s+meth'
    r'|zyn|cigarettes?|vaping|vapes?|e-?cig\w*'
    r'|tobacco\s+(?:ban|industry|product|compan|giant|firm|pouch|use|control|tax|advert|smok)\w*'
    r'|smoking\s+(?:ban|kills|cessation|rates?)|(?:stop|quit|anti).?smoking'
    r'|nicotine\s+(?:pouch|addict\w*|product|patch|gum|replacement|hit|craving|delivery|content)'
    r'|hiv\b'
    r'|aids[\s-]?(?:free|epidemic|virus|patients?|crisis|diagnosis|treatment|deaths?|pandemic|generation|drugs?)'
    r'|hitler\b'
    r'|sex\s+life|sex\s+lives'
    r'|sex\s+and\s+the\s+city'          # adult TV show personality quiz
    r'|sopranos|breaking\s+bad|game\s+of\s+thrones|succession\s+character'  # adult TV quizzes
    r')\b',
    re.I
)

# Hard-reject commercial/shopping/promo titles (score penalty not enough — science +5 overrides it)
# Also rejects newsletter roundup formats (The Download, DeBriefed, etc.) and media-reaction meta-articles
_COMMERCIAL_TITLE_RE = re.compile(
    r'(?:'
    r'deals?\s+(?:are\s+)?ending|prime\s+deals?|prime\s+day'
    r'|last\s+day\s+to\s+save|last\s+chance\s+to\s+(?:save|buy|get)'
    r'|save\s+(?:up\s+to|\d+%?)\s+on|best\s+(?:deals?|prices?)\s+on'
    r'|limited.time\s+offer|shop\s+now|buy\s+now\s+and\s+save'
    r'|black\s+friday|cyber\s+monday'
    r'|^the\s+download[\s:]'            # MIT Tech Review newsletter
    r'|^debriefed\s+\d'                 # Carbon Brief dated newsletter
    r'|^media\s+reaction[\s:]'          # Carbon Brief media-roundup
    r'|^\w+\s+briefing\s+\d'            # Regional briefings (China Briefing 25 June, US Briefing…)
    r'|\bnews\s+brief\b'                # Morning/evening news brief roundups (NPR etc.)
    r'|^morning\s+edition[\s:]'         # NPR Morning Edition teasers
    r'|^this\s+week\s+on\s+'            # "This week on The Hill" / "This week on X" roundups
    r'|^[¿¡]'                           # Non-English articles (Spanish inverted punctuation)
    r'|^watch\s+newsround'              # BBC Newsround video-promo stub articles
    r'|wine\s+club'                      # wine-lifestyle content (not for kids)
    r'|oatmeal\s+(?:chocolate\s+chip\s+)?cookie|chocolate\s+chip\s+cookie'  # recipe content
    r'|favorite\s+(?:recipe|oatmeal|cookie|meal)'  # personal recipe articles
    r'|(?:joined|won\'t\s+last).*wine\s+club'  # wine-lifestyle narratives
    r'|\bsheriff\s+addresses\b|\bsheriff.*latest\b'  # local-crime investigation news
    r'|pbm\s+lobby|pharmacy\s+benefit\s+manag'  # adult healthcare-policy lobbying
    r'|\bredistricti(?:ng|on)\s+ballot\b'  # local redistricting political news
    r'|dug\s+through.*deals?|last.minute.*deals?'  # last-minute deal roundups
    r'|\bfilming\s+locations?\b'                 # TV/movie tourism ("6 House of Dragon filming locations")
    r'|\bhighest.paid\s+job|best.paid\s+jobs?|highest.paying\s+job'  # adult salary content
    r'|\bin\s+every\s+state.{0,15}mapped|mapped.{0,15}every\s+state'  # adult data maps
    r'|\bsigns\s+with\s+\w|\btransfer\s+(?:fee|window|deal)\b'  # sports transfer gossip
    r'|\bscotus\b'                               # Supreme Court partisan politics
    r'|\brevenge\s+dress\b'                      # celebrity fashion events
    r'|quiz\s*:\s*which\s+\w+\s+character\s+are\s+you'  # adult TV personality quizzes
    r'|\bwhich\s+\w+\s+character\s+are\s+you\b'  # alternate quiz title pattern
    r'|quiz\s*:\s*only\s+true\s+\w+\s+fans?\s+know'  # celebrity fan trivia quizzes
    r'|\bonly\s+true\s+\w+\s+fans?\s+(?:know|can|will)\b'  # fan trivia quiz patterns
    r'|\bseniors?\s+(?:are|most|least).{0,30}outlive\b'  # adult retirement/aging data
    r'|\boutlive\s+their.{0,20}savings?\b'       # adult financial planning content
    r'|\bhoroscope\b|\bweekly\s+horoscope\b|\bastrology\s+(?:forecast|column)\b'  # pseudoscience
    r'|\branked\s+by\s+rotten\s+tomatoes\b'      # entertainment movie rankings
    r'|\bfavorite\s+fast\s+food\s+(?:chain|restaurant)\b'  # fast food commercial content
    r'|\bmortgage\s+rates?\s+(?:frustrate|hurt|rise|climb)\b'  # adult real estate
    r'|\bhomes?\s+(?:harder|slower)\s+to\s+sell\b'  # adult housing market
    r'|\b(?:craft\s+(?:beer|ipa|ale|lager|stout)|whiskey|whisky|bourbon|cocktail|spirits?)\b'  # alcohol content
    r'|\b(?:third\s+trimester|postpartum|baby\s+formula|best\s+stroller|maternity\s+leave)\b'  # pregnancy/parenting
    r'|\b(?:bitcoin|ethereum|crypto(?:currency)?|nft\s+(?:drop|mint)|web3)\b'  # crypto/NFT adult investing
    r'|\b(?:index\s+fund|roth\s+ira|401k|hedge\s+fund|dividend\s+yield)\b'  # adult investing content
    r'|\b(?:ufc\s+\d+|boxing\s+results?|knockou?t\s+(?:win|loss)|canelo|fury\s+vs|usyk)\b'  # combat sports
    r'|\bin\s+memoriam\b|\bremembering\s+\w+.{0,15}years?\s+later\b'  # obituary/tribute format
    r'|\bfda\s+panel\b|\bfda\s+advisory\b'      # adult FDA regulatory panel coverage
    r'|\b(?:peptide|semaglutide|ozempic|wegovy|mounjaro)\b'  # adult weight-loss drug content
    r'|\b(?:bodybuilding|testosterone\s+boost|muscle\s+mass\s+loss|anti.aging\s+protocol)\b'  # adult biohacking
    r'|^watch\s*:\s+how\s+to'                   # tutorial video stub articles ("Watch: How to...")
    r'|\bgel\s+nails?\b'                         # adult beauty/cosmetic content
    r'|\bdaca\s+recipients?\b|\bdreamers?\s+(?:face|struggle|fight)\b'  # immigration policy
    r'|\bnhs\s+maternity\b|\bmaternity\s+(?:scandal|inquiry|crisis)\b'  # UK healthcare politics
    r'|\binquiry\s+demands\s+nhs\b'               # NHS inquiry news
    r'|\bpeople\s+prefer\s+negotiating\b'          # adult workplace gender psychology
    r'|\baverage\s+salary.{0,30}(?:rent|state|ranked)\b'  # adult housing/finance content
    r'|\brequired\s+bible|bible\s+stories?\s+(?:in|for|required|at)\b'  # church-state curriculum
    r'|\bchurch\s+and\s+state\b|\bseparation\s+of\s+church\b'  # church-state controversy
    r'|\bsongs?\s+you\s+(?:might\s+not\s+know|didn\'t\s+know).{0,20}wrote\b'  # celebrity song trivia
    r'|(?:headphone|earbud|speaker|laptop|tablet|appliance|gadget)s?\s+sale\b'  # consumer tech retail sales
    r'|(?:fourth\s+of\s+july|4th\s+of\s+july|independence\s+day|labor\s+day|memorial\s+day|presidents\s+day)\s+.{0,40}sale\b'  # holiday sales (word or numeric form)
    r'|(?=.*\b(?:home\s+depot|walmart|target|best\s+buy|costco|lowe\'?s|kohl\'?s|nordstrom)\b)(?=.*\b(?:sale|deals?|discounts?)\b).'  # retailer + sale/deal anywhere in title
    r'|\bwedding\s+(?:gifts?|guests?|presents?|registry|etiquette|budget)\b'  # adult wedding financial/etiquette content
    r'|\bhow\s+much\s+(?:should|do|to|did|would)\s+(?:you|we|i|they|he|she)\s+(?:gift|give|spend|pay|tip|budget|save|earn|cost)\b'  # personal-finance "how much should you gift/spend/pay" framing
    r'|\bhow\s+much.{0,20}gift\s+at\s+a\b'        # "how much should you gift at a wedding" framing
    r')',
    re.I
)

# Hard-reject world news topics that are NEVER appropriate for a kids' news site.
# Applied ONLY to non-science articles (world news) in the main loop.
_WORLD_NEWS_REJECT_RE = re.compile(
    r'(?:'
    r'\blive\s+results?:\s'                   # "Live Results: Colorado primaries..."
    r'|(?:midterm|primary|election)\s+(?:results?|primaries|vote|live)'  # election results
    r'|\bprimar(?:y|ies)\s+(?:live|results?|election|vote)' # more election variants
    r'|\bjudge\s+delay'                        # "judge delays sentencing"
    r'|\bsentencing\s+(?:hearing|delayed?|phase)' # court sentencing news
    r'|\b(?:murder|assault|rape|kidnap)\s+trial\b' # criminal trial coverage
    r'|\byears?\s+in\s+(?:\w+\s+)?(?:prison|jail)'      # "X years in [US] prison/jail" - sentencing coverage
    r'|\b\d+\s+years?\s+in\s+(?:\w+\s+)?(?:prison|jail)' # "30 years in US prison" — number + qualifier
    r'|\bsentenced\s+to\s+(?:\d+|life|two|three|four|five)\b' # "sentenced to N years"
    r'|\bgets?\s+(?:life|\d+\s+)?years?\s+in\s+(?:\w+\s+)?(?:prison|jail)' # prison sentence results
    r'|\b(?:convicted|jailed|imprisoned)\s+(?:for|over|in)\b' # conviction framing
    r'|\bdied\s+of\s+(?:aids?|hiv|cancer|drug|overdose|covid)' # celebrity death + disease
    r'|\bcause\s+of\s+death\s+(?:was|is|revealed|confirmed)\b'  # "cause of death was X"
    r'|\b(?:actress|actor|celebrity|star)\s+(?:died?|dead|passes?\s+away|passes?)' # celebrity death
    r"|'s\s+cause\s+of\s+death"                # "Chase's cause of death was..."
    r'|\b(?:asylum|refugee)\s+(?:seeker|repay|repatriat|detain|flee|policy)' # asylum policy
    r'|\brefugees?\s+will\s+be'               # "Refugees will be told..."
    r'|\bimmigration\s+(?:crackdown|enforcement|policy|ban|ban)' # immigration enforcement
    r'|\bborder\s+(?:crisis|crossing|enforcement|crackdown)' # border enforcement
    r'|\b(?:deported?|deportation|deportees?)\s+(?:by|from|to|back)\b' # deportation news
    r'|\bserial\s+killer\b'                   # serial killer coverage
    r'|\bmass\s+(?:shooting|murder|killing)\b' # mass violence events
    r'|\btemporary\s+protected\s+status\b'    # immigration status policy
    r'|\bprotected\s+status\s+program\b'       # immigration program policy
    r'|\b(?:anti.corruption|corruption)\s+crackdown\b' # foreign political crackdowns
    r'|\bsave\s+america\s+act\b'               # specific US partisan legislation
    r'|\b(?:doge|department\s+of\s+government\s+efficiency)\b' # US partisan agency
    r'|\bconcedes?\s+(?:save|big|beautiful)\s+america\b' # specific bill negotiation
    r'|\b(?:indicted?|indictment)\b'           # criminal indictment news
    r'|\bfraud\s+(?:allegations?|charges?|case)\b' # financial fraud proceedings
    r'|\b(?:gambling|bribery|extortion)\s+(?:scheme|ring|case|scandal|charges?|indictment)\b' # crime
    r'|\bmortgage\s+fraud\b'                   # mortgage fraud coverage
    r'|\bcriminal\s+(?:charges?|allegations?|conspiracy)\b' # criminal proceedings
    r'|\bdemocrats?\s+(?:accuse|accuses?|blast|slam|attack|criticize)\s+(?:trump|gop|republicans?)\b'  # partisan Democrat-vs-Republican accusation framing
    r'|\brepublicans?\s+(?:accuse|accuses?|blast|slam|attack|criticize)\s+(?:democrats?|biden|harris)\b'  # partisan GOP-vs-Democrat accusation framing
    r'|\b(?:house|senate)\s+democrats?\s+(?:accuse|blast|slam|attack|demand|warn|call\s+out)\b'  # Congressional Democrats making partisan attacks
    r'|\b(?:house|senate)\s+republicans?\s+(?:accuse|blast|slam|attack|demand|warn|call\s+out)\b'  # Congressional Republicans making partisan attacks
    r'|\b(?:governor|senate|house|congressional)\s+(?:nominee|primary|candidate|race)\b'  # election race content — always partisan
    r'|\bgov(?:ernor)?\s+nominee\b'               # governor nominee specifically
    r'|\bDSA\s+(?:candidate|member|nominee|backed?|wing|endorsed?)\b'  # Democratic Socialists candidate references
    r'|\bjack\s+smith\s+(?:says?|claims?|warns?|blasts?|slams?|attacks?|criticizes?|calls?|reveals?|speaks?|writes?|testifies?)\b'  # Jack Smith (former special counsel) political commentary
    r'|\b(?:special\s+counsel|special\s+prosecutor)\s+(?:jack\s+)?smith\b'  # special counsel Smith references
    r'|\binquest\s+(?:adjourned|delayed|resumed|verdict|into|hears?|finds?|concludes?|opens?|returns?|jury)\b'  # death inquest legal proceedings
    r'|\bgrand\s+jury\b'                          # grand jury = criminal proceedings, always legal/political
    r'|\bindictment\b'                            # indictment = criminal charge filing, always legal/political
    r'|\bfelony\b'                                # felony = serious criminal charge, always legal/political
    r'|\bpelosi\b|\bnancy\s+pelosi\b'          # partisan political figure (hard block)
    r'|\bpelosi\s+institute\b'                 # named partisan institution
    r'|\bpirro\b'                              # Jeanine Pirro — Trump-appointed US Atty DC, partisan (hard block)
    r'|\bencourag\w+\s+drugg'               # forums/groups encouraging drugging (drink spiking, criminal activity)
    r'|\btrump\s+(?:signs?|pushes?|demands?|orders?|calls?|launches?|announces?|unveils?)\b' # partisan executive action
    r'|\btrump\s+accounts?\b'                  # "Trump Accounts" savings policy (partisan executive branding)
    r'|\bwhite\s+house\s+(?:to\s+)?(?:launch|announce|unveil|roll\s+out)\b'  # White House policy rollout news
    r'|\bpensions?\b'                          # pensions = adult financial/policy topic, never kid content
    r'|\bcoalition\s+(?:agree|agrees|agreed|deal|govern|government|talks?|reach\w*|collaps\w*|partner\w*)\b'  # government coalition politics
    r'|\btax\s+(?:reform|cut|cuts|hike|rise|bill|change|changes|plan|policy|deal|break|code|law)\w*'  # tax-policy legislation
    r'|\b(?:income|corporate|pension|inheritance|payroll)\s+tax\b'  # specific tax-policy framings
    r'|\bSNP\b'                               # Scottish National Party (political)
    r'|\btor(?:y|ies)\b'                       # UK Conservative Party (political)
    r'|\blabour\s+(?:party|leader|mp|government|manifesto)\b'  # UK Labour party politics
    r'|\bconservative\s+(?:party|leader|mp|government|manifesto|leadership)\b'  # UK Conservative party politics
    r'|\bleadership\s+(?:contest|race|bid|challenge|campaign|battle|hopeful|rival)\b'  # party leadership politics
    r'|\bparty\s+leader(?:ship)?\b'            # party leader/leadership (political)
    r'|\bhosepipe\b'                           # UK water-restriction regional utility news
    r'|\bhorse\s?meat\b'                       # food-fraud / adulteration investigation
    r'|\bset(?:s|ting)?\s+(?:himself|herself|themselves|itself|oneself|self)\s+(?:on\s+fire|alight|ablaze)\b'  # self-immolation (graphic)
    r'|\bself.immolat\w*'                      # self-immolation
    r'|\bsuicide\b|\bself.harm\b'              # suicide / self-harm content
    r'|\b(?:man|men|woman|women|boys?|girls?|teenagers?|workers?|persons?|people|migrants?|villagers?|children|kids?|students?|tourists?|passengers?)\s+(?:dies?|died|killed|dead|found\s+dead|burns?\s+to\s+death|shot\s+dead)\b'  # human death / tragedy news
    r'|\bdies?\s+after\s+(?:setting|being|a\s+|an\s+|falling|crash|stabb|shoot|attack)'  # tragic death circumstances
    # --- Proactive safety block: violence / war / disaster / graphic-health (bounded to avoid science/nature collisions) ---
    r'|\bstab(?:s|bed|bing)\b|\bgunmen?\b|\bgunfire\b|\bopens?\s+fire\b|\bshot\s+dead\b'
    r'|\bmass\s+shooting\b|\bshootings?\s+(?:at|in|spree|rampage|leaves?|kills?|dead|wounds?)\b'
    r'|\barmed\s+(?:robber|robbery|raid|gang|attacker|assailant)\b|\bgang\s+(?:violence|war|shooting|rape|members?)\b'
    r'|\bknife\s+(?:attack|crime|rampage|wielding)\b|\bmachete\b'
    r'|\bairstrikes?\b|\bair\s+strikes?\s+(?:hit|kill|target|pound|destroy|level|near|on|against|leave|in|rock|pummel)\b'
    r'|\bmissile\s+(?:strike|attack|barrage|hits?|fired|launch)\b|\bshelling\b|\bceasefire\b'
    r'|\b(?:government|rebel|enemy|army|ground|foreign)\s+troops\b|\btroops\s+(?:advance|deploy|invade|withdraw|clash|kill|open\s+fire|storm|enter)\b'
    r'|\bsoldiers?\s+(?:killed|dead|die|died|wounded|injured|ambush)\b|\bdrone\s+(?:strike|attack)\b'
    r'|\bterror(?:ist|ism)?\s+(?:attack|plot|cell|suspect|threat|group|network)\b|\bterrorists?\b|\bhostages?\b'
    r'|\b(?:car|suicide|pipe|nail|roadside)\s+bomb\w*|\bbomb(?:ing)?\s+(?:attack|blast|kills?|hits?|targets?|rips?|near)\b|\bbomb\s+explodes?\b'
    r'|\b(?:man|woman|boy|girl|toddler|child|teen|teenager|baby|infant|pensioner|hiker|climber|swimmer)\s+drowns?\b|\bdrowns?\s+in\s+(?:a\s+|the\s+)?(?:pool|river|sea|lake|canal|bath)\b'
    r'|\bplane\s+crash(?:es|ed)?\b|\bair\s+crash\b|\bjet\s+crash\b'
    r'|\b(?:bus|coach|ferry|boat|train|lorry|truck|minibus|van)\s+(?:crash|plunge|derail|capsiz|falls?|topple|overturn)\w*'
    r'|\bcrash\s+kills?\b|\bkilled\s+in\s+(?:a\s+)?(?:crash|collision|accident|blast)\b|\bbuilding\s+collapse\b|\bcollapse\s+kills?\b'
    r'|\bkill(?:s|ed|ing)\s+(?:dozens|hundreds|thousands|scores)\b'
    r'|\bfatal\s+(?:\w+\s+){0,2}(?:fire|blaze|crash|collision|accident|shooting|stabbing|fall)\b|\bclaims?\s+(?:the\s+)?(?:life|lives|famil\w+)\b'
    r'|\bbodies\s+(?:found|recovered|pulled|discovered)\b|\bmass\s+grave\b'
    r'|\b(?:burn(?:ed|t)|hacked|beaten|stabbed|frozen|choked|starved|crushed)\s+to\s+death\b|\bfound\s+(?:frozen|hanged|strangled|stabbed)\b'
    r'|\b(?:\d+|two|three|four|five|six|seven|eight|nine|ten|dozens?|scores|hundreds|several|many)\s+(?:feared\s+)?dead\b(?!\s+(?:languages?|sea|stars?|zones?|ends?|planets?))'
    r'|\b(?:buries|buried|engulf\w+|swallow\w+|flatten\w+|devastat\w+|wipes?\s+out)\s+(?:a\s+|the\s+|entire\s+)?(?:village|town|city|homes?|houses?|neighbou?rhood|community|families)\b'
    r'|\b(?:human|sex|child|drug|people)\s+trafficking\b|\bgrooming\s+(?:teens?|children|kids|minors|young|a\s+(?:child|teen|minor|girl|boy))\b|\bchild\s+(?:abuse|sex|porn)\w*'
    r'|\b(?:earthquake|quake|flood|landslide|wildfire|hurricane|tornado|cyclone|tsunami|mudslide|avalanche)\s+(?:kills?|victims?|deaths?|dead|death\s+toll|survivors?)\b|\bdeath\s+toll\b'
    r'|\bdeadly\s+(?:virus|disease|outbreak|bug|infection|pandemic|epidemic|flu|attack|blast|crash|fire|flood|storm|strain)\b'
    r'|\b(?:virus|disease|ebola|cholera|measles|plague|smallpox)\s+(?:outbreak|kills?|claims?|spreads?|death\s+toll)\b|\boutbreak\s+(?:kills?|spreads?|deaths?|grips?|sickens?)\b'
    r'|\bcancer\s+patient\b|\bterminally\s+ill\b|\bdying\s+(?:man|woman|boy|girl|child|wish)\b'
    r'|\bkhamenei\b|\bayatollah\b|\bworld\s+leaders?\b|\bkebabs?\b'
    r'|\bgorsuch\b|\bkavanaugh\b|\balito\b|\bsotomayor\b|\bsupreme\s+court\b|\bscotus\b'  # SCOTUS justices / court (political)
    r'|\btransgender\s+(?:rights|advocates?|policy|ban|athletes?|law|ruling|case|movement|community|troops|military|surgery)\b|\btrans\s+(?:rights|athletes?|ban)\b'  # trans-rights political/legal litigation
    r'|\bthe\s+memo:'                          # The Hill political opinion column
    r'|\bclashing\s+visions\b|\bnation.?s\s+(?:divide|divisions?)\b'  # political-divide opinion framing
    r'|\bnews\s+quiz\b'                        # branded external news quizzes (site has its own games)
    r'|\bvoters?\b|\breform\s+(?:proposals?|package|bill|agenda|plan)\w*'  # electorate / policy-reform politics
    # --- Corpus-audit gap closers: obituaries / ministers / courts / outbreaks / unrest ---
    r'|\bdies?\s+aged\s+\d{1,3}\b|\bdies?\s+at\s+(?:the\s+age\s+of\s+)?\d{1,3}\b|\bdead\s+at\s+\d{1,3}\b'  # obituaries
    r'|\b\d{1,2}[\s-]year[\s-]olds?\s+(?:dies?|died|killed|dead|drowns?)\b'  # "18-year-old dies"
    r'|\b(?:firefighters?|police\s+officers?|paramedics?|miners?|climbers?|divers?|passengers?|pilots?)\s+(?:dies?|died|killed|dead)\b'
    r'|\bkill(?:s|ed|ing)\s+(?:at\s+least\s+)?(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b'  # small casualty counts (word-form, avoids "kills 99%")
    r'|\bprime\s+minister\b|\bforeign\s+minister\b|\bminister\s+(?:quits|resigns?|resigned|vows|warns)\b|\b(?:finance|defen[cs]e|health|home|interior|culture|deputy|justice)\s+minister\b'
    r'|\bfederal\s+court\b|\bappeals\s+court\b|\bcircuit\s+court\b|\bhigh\s+court\b|\bfederal\s+jury\b|\bjury\s+(?:selection|deliberat|plans)\b'
    r'|\btear\s+gas\b|\briot\s+police\b|\brubber\s+bullets?\b'
    r'|\b(?:norovirus|hantavirus|monkeypox|mpox|cholera|dengue)\b|\boutbreak\s+(?:linked|hits?|reported|declared)\b'
    r'|\btaxes?\s+on\b|\bwhole\s+hog\s+politics\b|\bpartisan\b|\bidentity\s+politics\b'  # grocery/consumption-tax policy, political columns
    r'|\bhuman\s+rights\s+(?:catastrophe|crisis|abuse|violation|disaster|emergency)|\bhumanitarian\s+(?:crisis|catastrophe|disaster|emergency)|\bwar\s+crimes?\b|\bethnic\s+cleansing\b|\batrocit\w+|\bcrimes?\s+against\s+humanity\b'  # humanitarian / conflict-atrocity crisis
    r'|\b(?:re)?arrests?\s+(?:prominent|leading|opposition|top|\w+\s+)?(?:activists?|journalists?|dissidents?|protesters?|critics?|conservationists?|lawyers?|campaigners?|bloggers?)\b|\b(?:journalists?|activists?|protesters?|dissidents?|critics?|conservationists?|campaigners?)\s+(?:detained|arrested|jailed|imprisoned)\b|\bpolitical\s+prisoners?\b|\bfamine\b|\bmass\s+starvation\b'  # political arrests / persecution, famine
    r'|\b(?:comic|comedian|cartoonist|writer|author|singer|artist|actor|blogger|poet|rapper)\s+(?:held|detained|arrested|jailed|charged|questioned|convicted|sentenced)\b|\bheld\s+for\s+(?:jokes|posts|tweets|comments|cartoons|criticism|insulting|a\s+joke)\b'  # creatives detained for speech (free-speech persecution)
    r'|\berdogan\b|\bputin\b|\bxi\s+jinping\b|\bkim\s+jong\b|\blukashenko\b|\bmaduro\b'  # authoritarian world leaders (political)
    r'|\b(?:last|dying|final)\s+words\s+to\b|\bdeathbed\b|\bdying\s+words\b'  # deathbed / celebrity last-words content
    r'|\bjustice\s+department\b|\bDOJ\b|\bunredact\w+|\bredacted\s+(?:documents?|files?|report|version)'  # DOJ / redacted legal documents
    r'|\btrump\s+(?:to\s+)?(?:headline|rally|rallies|campaign|visit|attend|host|hold|tout|vow|slam|blast|celebrat|declar)\w*'  # Trump political events (extends existing Trump verb filter)
    r'|\bmamdani\b|\bhouthis?\b|\bmilitia\b|\binsurgenc\w+'  # named politician / militant groups
    r'|\bexcess\s+deaths?\b|\b\d[\d,]{2,}\s+deaths?\b'  # mass-mortality / death-toll statistics
    r'|\bforces?\s+(?:thousands|hundreds|residents|families|people|locals)\s+to\s+(?:evacuate|flee)\b|\bmass\s+evacuation\b|\b(?:wildfire|blaze|bushfire|flood|hurricane|volcano)\s+(?:forces|prompts|triggers|sparks)\s+(?:evacuation|thousands)\b'  # disaster mass-evacuation news
    r'|\bfarage\b|\bby-?elections?\b|\bresigns?\s+as\s+(?:an?\s+)?MP\b|\bMPs?\s+(?:resign|quit|vow|demand|debate|clash|defect|suspend)\w*'  # UK MP / by-election politics
    r'|\ble\s+pen\b|\btop\s+court\b|\bpresidency\b|\brun\s+for\s+(?:president|presidency|office|governor|mayor|congress|senate|parliament|the\s+white\s+house)\b'  # named politician / highest court / running for office
    r'|\bbiden\s+(?:signs?|pushes?|accuses?|orders?|admits?)\b' # partisan executive action
    r'|\brfk\s*jr\b'                            # US health secretary, always partisan
    r'|\b(?:maga|anti.maga|far.right|far.left|ultra.maga)\b' # partisan label content
    r'|\bbreaking\s+promises\b|\baccusing\s+(?:him|her)\s+of\b' # political drama framing
    r'|\boligarc?hs?\b'                            # oligarch stories (mob/political violence)
    r'|\b(?:injured|wounded|shot)\s+in\s+(?:blast|explosion|bomb|attack|shooting|ambush)\b' # violence event casualties
    r'|\bpolice\s+(?:hunt|chase|seek|search)\s+(?:for\s+)?(?:suspect|gunman|attacker|killer)\b' # police manhunt
    r'|\bhunt\s+for\s+(?:suspect|gunman|attacker|killer)\b' # suspect manhunt framing
    r'|\b(?:two|three|four|five|six|seven|eight|nine|ten|\d+)\s+(?:wounded|killed|dead|injured)\s+in\b' # mass casualty framing
    r'|\b(?:assassination|assassin(?:ated)?)\b'    # assassination/political violence
    r'|\b(?:mob|cartel|mafia|gangster)\s+(?:boss|leader|war|hit|killing)\b' # organized crime
    r'|\b(?:stabbing|knife\s+attack|gun(?:man|men)|gunshot|gun(?:fight|battle))\b' # violent crime acts (NOT "shootout" = penalty shoot-out in sports)
    r'|\bdrone\s+(?:hits?|strikes?|attack|kill|killed|struck|crash)\b' # drone strike/war news
    r'|\b(?:airstrike|air\s+strike|missile\s+strike|missile\s+attack|bombing\s+raid)\b' # air/missile attacks
    r'|\b(?:Zaporizhzhia|Bakhmut|Kharkiv|Mariupol)\b'  # active Ukrainian war zone cities
    r'|\b(?:anti.migrant|anti.immigrant)\s+(?:protests?|protesters?|violence|sentiment|riot|march|rally|rallies)\b' # xenophobic protest news
    r'|\bwarns?\s+anti.migrant\b'  # government warning anti-migrant groups
    r'|\bgrooming\s+gang\b'  # child exploitation criminal content
    r'|\bstalker\s+who\b|\bstalking\s+(?:victim|case|charges?|arrest)\b'  # stalker crime content
    r'|\b(?:undocumented\s+migrants?|undocumented\s+foreigners?)\s+(?:flee|fear|face|targeted?)\b'  # xenophobic targeting framing
    r'|\b(?:accuse[sd]?|accusing|blames?|blaming)\s+(?:\w+\s+){0,3}(?:government|authorities|president|regime|administration)\s+of\b'  # political accusation framing
    r'|\b(?:government|regime|administration)\s+(?:negligence|incompetence|apathy|corruption|cruelty|failure)\b'  # government failure framing
    r'|\b(?:negligence\s+and\s+apathy|apathy\s+and\s+negligence)\b'  # political failure narrative
    r'|\b(?:conducts?|launches?|carries?\s+out)\s+(?:military\s+)?strikes?\s+(?:on|against|in)\b'  # military strike ops
    r'|\bexchange\s+of\s+(?:fire|strikes?|attacks?)\s+(?:with|between)\b'  # mutual military exchange
    r'|\bstand\s+down\s+after\s+(?:exchange|strikes?|attack|conflict)\b'  # military de-escalation framing
    r'|\bstrikes?\s+(?:on|against)\s+(?:Iran|Iraq|Syria|Yemen|Gaza|Pakistan|Afghanistan|Somalia|Libya|Sudan|North\s*Korea)\b'  # named-country military strikes
    r'|\bStrait\s+of\s+Hormuz\b'               # geopolitical military chokepoint — always conflict/Iran context
    r'|\bseized?\s+(?:ships?|vessels?|tankers?)\b'  # military/geopolitical seizure of ships
    r'|\bMK.Ultra\b|\bMKUltra\b'  # CIA mind control program — not kid-appropriate
    r'|\bCIA\s+(?:mind\s+control|human\s+experiment|torture|interrogation|drug\s+test|secret\s+program)\b'  # CIA black programs
    r'|\bexplosive\s+diarrhea\b'  # sensationalist gut-health clickbait
    r'|^fox\s+news\s+poll\s*:'    # partisan polling content
    r'|\bICE\s+(?:surges?|raids?|sweeps?|makes?\s+\d+|arrests?\s+\d+)'  # ICE enforcement news
    r'|\bper\s+hour.{0,50}\bmapped\b|\bmapped\b.{0,50}\bper\s+hour\b'  # adult earnings-data maps ("make per hour, mapped")
    r'|\bmost\s+per\s+hour\b'                      # "make the most per hour" earnings rankings
    r'|\b(?:job|labor|labour)\s+market\s+(?:slows?|cools?|tightens?|weakens?|surges?|grows?|adds?|loses?|shrinks?|report)\b'  # adult economic job market news
    r'|\bemployers?\s+(?:pulled?\s+back|slow\w*|cut|shed|add\w*)\b.{0,40}\bhiring\b'  # adult hiring trend news
    r'|\b(?:payroll|hiring|employment)\s+(?:data|report|numbers?|growth|falls?|slows?|gains?|rose|fell|dropped?|cooled?|picked\s+up|shows?|weakness|strength)\b'  # payroll/hiring/employment data reports
    r'|\b(?:us|u\.s\.)\s+employers?\s+(?:pulled?\s+back|add\w*|cut|shed|hired?)\b'  # US employer action headlines
    r')',
    re.I
)

# Active branch — set to a content branch in main(); falls back to "main" locally
ACTIVE_BRANCH = "main"

if not GITHUB_TOKEN:
    raise SystemExit("GITHUB_TOKEN not found: set env var or add to projects/API-KEYS.env")

# ── GitHub Contents API ────────────────────────────────────────────────────────
def gh(method, path, body=None, _retry=3):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        f"https://api.github.com{path}", data=data,
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "User-Agent": "kd-scraper",
                 "Accept": "application/vnd.github+json", "Content-Type": "application/json"},
        method=method)
    for attempt in range(_retry):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=25, context=ctx).read())
        except urllib.error.HTTPError as e:
            body_text = e.read().decode()[:400]
            # Retry on server errors and "malformed request" transients
            is_transient = e.code >= 500 or (e.code == 400 and "malformed" in body_text.lower())
            if is_transient and attempt < _retry - 1:
                time.sleep(4 + attempt * 3)
                continue
            return {"_err": e.code, "_body": body_text}
        except OSError:
            if attempt < _retry - 1:
                time.sleep(3 + attempt * 2)
            else:
                raise

def upload(repo_path, content_str, message):
    branch = ACTIVE_BRANCH
    existing = gh("GET", f"/repos/{REPO}/contents/{repo_path}?ref={branch}")
    sha = existing.get("sha") if isinstance(existing, dict) and not existing.get("_err") else None
    encoded = base64.b64encode(content_str.encode("utf-8")).decode()
    payload = {"message": message, "content": encoded, "branch": branch}
    if sha:
        payload["sha"] = sha
    r = gh("PUT", f"/repos/{REPO}/contents/{repo_path}", payload)
    sha_short = r.get("commit", {}).get("sha", "")[:8] if "commit" in r else None
    if sha_short:
        print(f"  ✓ {repo_path} ({len(content_str):,}b) → {sha_short}")
    else:
        print(f"  ✗ {repo_path}: {r.get('_body', str(r))[:150]}")
    time.sleep(0.5)
    return sha_short

# ── GitHub Flow helpers ────────────────────────────────────────────────────────
def setup_content_branch(today):
    """Create content/daily-news-{today} branch off main; set ACTIVE_BRANCH."""
    global ACTIVE_BRANCH
    branch = f"content/daily-news-{today}"
    r = gh("GET", f"/repos/{REPO}/git/ref/heads/main")
    if r.get("_err"):
        print(f"  ⚠ Cannot get main SHA ({r.get('_err')}), pushing to main directly")
        return
    main_sha = r["object"]["sha"]
    result = gh("POST", f"/repos/{REPO}/git/refs", {
        "ref": f"refs/heads/{branch}", "sha": main_sha,
    })
    if result.get("_err") == 422:
        print(f"  Branch {branch} already exists — reusing")
    elif result.get("_err"):
        print(f"  ⚠ Branch create failed ({result.get('_err')}), pushing to main directly")
        return
    else:
        print(f"  Created branch: {branch}")
    ACTIVE_BRANCH = branch

def create_and_merge_pr(today, n_articles):
    """Open a PR from the content branch → main, then immediately squash-merge it."""
    branch = ACTIVE_BRANCH
    if branch == "main":
        return  # no-op when running locally without branch setup
    pr = gh("POST", f"/repos/{REPO}/pulls", {
        "title": f"Daily news: {today} — {n_articles} new article{'s' if n_articles != 1 else ''}",
        "head": branch, "base": "main",
        "body": (
            f"## Automated daily news update\n\n"
            f"- Date: {today}\n"
            f"- New articles: {n_articles}\n"
            f"- Generated by KiddieDaily Scraper\n\n"
            f"_This PR is auto-generated. CI validates HTML, sitemap, and JSON before merge._"
        ),
    })
    if pr.get("_err"):
        print(f"  ⚠ PR create: {pr.get('_body', '')[:200]}")
        return
    pr_num = pr["number"]
    pr_url = pr.get("html_url", "")
    print(f"  PR #{pr_num} opened: {pr_url}")
    time.sleep(2)  # give CI a moment to register
    merge = gh("PUT", f"/repos/{REPO}/pulls/{pr_num}/merge", {
        "merge_method": "squash",
        "commit_title": f"chore(content): daily news {today} ({n_articles} articles) [auto]",
        "commit_message": f"Automated content update via scraper. PR #{pr_num}.",
    })
    if merge.get("merged"):
        print(f"  PR #{pr_num} squash-merged ✓ → main")
        # Delete the content branch to keep repo clean
        gh("DELETE", f"/repos/{REPO}/git/refs/heads/{branch}")
        print(f"  Branch {branch} deleted")
    else:
        print(f"  ⚠ Merge pending (CI may be blocking): {merge.get('message', '')}")

# ── RSS sources with AllSides / Ad Fontes Media bias ratings ──────────────────
# bias: -2=far-left  -1=left  0=center  +1=right  +2=far-right
SOURCES = [
    {"name": "BBC News",      "url": "http://feeds.bbci.co.uk/news/rss.xml",                   "bias": -0.3, "icon": "🇬🇧"},
    {"name": "NPR",           "url": "https://feeds.npr.org/1001/rss.xml",                      "bias": -0.7, "icon": "📻"},
    {"name": "Al Jazeera",    "url": "https://www.aljazeera.com/xml/rss/all.xml",              "bias": -0.4, "icon": "🌍"},
    {"name": "The Hill",      "url": "https://thehill.com/news/feed/",                          "bias":  0.1, "icon": "⚖️"},
    {"name": "Fox News",      "url": "https://moxie.foxnews.com/google-publisher/latest.xml",   "bias":  1.3, "icon": "🦅"},
    {"name": "DW News",       "url": "https://rss.dw.com/rdf/rss-en-all",                    "bias": -0.1, "icon": "🌐"},
    {"name": "PBS NewsHour",  "url": "https://www.pbs.org/newshour/feeds/rss/headlines",        "bias": -0.2, "icon": "📺"},
    {"name": "NASA",          "url": "https://www.nasa.gov/rss/dyn/breaking_news.rss",          "bias":  0.0, "icon": "🚀"},
    {"name": "Science Daily", "url": "https://www.sciencedaily.com/rss/all.xml",               "bias":  0.0, "icon": "🔬"},
    {"name": "Smithsonian",   "url": "https://www.smithsonianmag.com/rss/latest_articles/",    "bias": -0.1, "icon": "🏛️"},
    # Extended science + educational sources (bias ≈ 0, topic-safe)
    {"name": "Science News",  "url": "https://www.sciencenews.org/feed",                       "bias":  0.0, "icon": "📡"},
    {"name": "EarthSky",      "url": "https://earthsky.org/feed/",                             "bias":  0.0, "icon": "🌏"},
    {"name": "Live Science",  "url": "https://www.livescience.com/feeds/all",                  "bias":  0.0, "icon": "🧬"},
    {"name": "ScienceAlert",  "url": "https://www.sciencealert.com/feed",                      "bias":  0.0, "icon": "⚛️"},
    {"name": "MIT News",      "url": "https://news.mit.edu/rss/research",                      "bias":  0.0, "icon": "🎓"},
    {"name": "New Scientist", "url": "https://www.newscientist.com/feed/home/",                "bias": -0.1, "icon": "🧪"},
    {"name": "Popular Science","url": "https://www.popsci.com/feed/",                          "bias":  0.0, "icon": "💡"},
    {"name": "Space.com",     "url": "https://www.space.com/feeds/all",                        "bias":  0.0, "icon": "🌌"},
    # Additional sources for underrepresented categories (history, environment, animals)
    {"name": "Ars Technica Science", "url": "https://feeds.arstechnica.com/arstechnica/science", "bias": -0.2, "icon": "🔭"},
    {"name": "Mongabay",      "url": "https://news.mongabay.com/feed/",                        "bias": -0.1, "icon": "🦁"},
    {"name": "JSTOR Daily",   "url": "https://daily.jstor.org/feed/",                          "bias": -0.1, "icon": "📚"},
    {"name": "NASA Earth",    "url": "https://earthobservatory.nasa.gov/feeds/earth-observatory.rss", "bias": 0.0, "icon": "🌍"},
    {"name": "Carbon Brief",  "url": "https://www.carbonbrief.org/feed/",                             "bias": -0.3, "icon": "🌿"},
    {"name": "MIT Tech Review","url": "https://www.technologyreview.com/feed/",                        "bias": -0.1, "icon": "💻"},
    {"name": "World History Encyclopedia", "url": "https://www.worldhistory.org/rss/",                "bias":  0.0, "icon": "📜"},
    {"name": "IEEE Spectrum",  "url": "https://spectrum.ieee.org/feeds/feed.rss",                  "bias":  0.0, "icon": "⚡"},
    # Environment deep-coverage (not in SCIENCE_SOURCES so political articles get filtered by score)
    {"name": "Inside Climate News", "url": "https://insideclimatenews.org/feed/",                  "bias": -0.4, "icon": "🌊"},
    # Academic journalism — science/space/tech explainers written by researchers
    {"name": "The Conversation",    "url": "https://theconversation.com/us/technology/articles.atom", "bias": -0.2, "icon": "🎓"},
    # Deep-dive science journalism: paleontology, space, ecology, evolution, discovery
    {"name": "Nautilus",            "url": "https://nautil.us/feed/",                                 "bias":  0.0, "icon": "🔵"},
    # Archaeology: AIA official news — excavations, discoveries, ancient civilizations
    {"name": "Archaeology",         "url": "https://www.archaeology.org/feed",                        "bias":  0.0, "icon": "🏺"},
    # Medieval history research: inventions, archaeology, manuscripts, Viking discoveries
    {"name": "Medievalists",        "url": "https://www.medievalists.net/feed/",                      "bias":  0.0, "icon": "⚔️"},
    # Popular history: Maya, Rome, Tudor, ancient empires, archaeological mysteries
    {"name": "HistoryHit",          "url": "https://www.historyhit.com/feed/",                        "bias":  0.0, "icon": "🗺️"},
    # Ocean + coastal science: marine life, deep-sea, ocean ecology, coastal environment
    {"name": "Hakai Magazine",      "url": "https://hakaimagazine.com/feed/",                         "bias":  0.0, "icon": "🌊"},
    # Math, physics, biology, CS — deep science for curious minds
    {"name": "Quanta Magazine",     "url": "https://www.quantamagazine.org/feed/",                    "bias":  0.0, "icon": "🔷"},
    # Kids news: BBC Newsround — gold standard children's news; animals, nature, world, science
    {"name": "BBC Newsround",       "url": "https://feeds.bbci.co.uk/newsround/rss.xml",              "bias": -0.1, "icon": "📺"},
    # Science magazine: Discover — animals, space, paleontology, environment, physics
    {"name": "Discover Magazine",   "url": "https://www.discovermagazine.com/rss/all",                "bias":  0.0, "icon": "🔬"},
    # Science journalism for ages 9-14: STEM, biology, physics, earth science, space, tech
    {"name": "Science News Students", "url": "https://www.snexplores.org/feed",                      "bias":  0.0, "icon": "🔭"},
    # Weird wonders of the world: unusual places, lost history, strange science, discoveries
    {"name": "Atlas Obscura",       "url": "https://www.atlasobscura.com/feeds/latest",              "bias":  0.0, "icon": "🗺️"},
    # Mental Floss: fun facts, trivia, history oddities, science curiosities
    {"name": "Mental Floss",        "url": "https://www.mentalfloss.com/rss.xml",                    "bias":  0.0, "icon": "🧠"},
    # Sci-News: archaeology, paleontology, astronomy, biology discoveries
    {"name": "Sci-News",            "url": "https://www.sci.news/feed",                              "bias":  0.0, "icon": "⚗️"},
    # Good News Network: uplifting, positive global news — environment, science, community
    {"name": "Good News Network",   "url": "https://www.goodnewsnetwork.org/feed/",                  "bias":  0.0, "icon": "🌍"},
    # SciTechDaily: science & technology news aggregator — archaeology, space, biology, physics
    {"name": "SciTechDaily",        "url": "https://scitechdaily.com/feed/",                         "bias":  0.0, "icon": "🏛"},
    # Berkeley News: UC Berkeley research — physics, biology, environment, technology
    {"name": "Berkeley News",       "url": "https://news.berkeley.edu/feed/",                        "bias":  0.0, "icon": "🎙️"},
    # ZME Science: accessible science for curious minds — animals, space, paleontology
    {"name": "ZME Science",         "url": "https://www.zmescience.com/feed/",                       "bias":  0.0, "icon": "🔬"},
    # Universe Today: astronomy and space science news — rockets, telescopes, planets
    {"name": "Universe Today",      "url": "https://www.universetoday.com/feed/",                   "bias": 0.0, "icon": "🔭"},
    # Wired Science: accessible tech + science explainers for general audience
    {"name": "Wired Science",       "url": "https://www.wired.com/feed/category/science/latest/rss", "bias":  0.1, "icon": "💡"},
]

# ── Kid-safety filter ──────────────────────────────────────────────────────────
BLOCKLIST = [
    "murder", "killed", "shooting", "massacre", "rape", "sexual assault",
    "suicide", "overdose", "cocaine", "heroin", "fentanyl",
    "explicit", "porn", "adult content",
    "war crime", "genocide", "torture", "execution", "beheading",
    "fatally", "death toll", "casualties", "bodies found",
    "die in", "dies in", "died in",
    # Hate groups and extremism (never appropriate for kids)
    "neo-nazi", "white supremac", "white nationalist", "white supremist",
    "kkk", "ku klux", "extremist group", "domestic terrorist",
    "hate group", "hate crime",
    # Psychedelics and drug compounds not appropriate for kids
    "magic mushroom", "psilocybin", "psilocin", "ayahuasca", "lsd trip",
]
SAFE_OVERRIDES = [
    "space", "science", "animal", "planet", "nature", "research",
    "invention", "discovery", "environment", "ocean", "climate",
    # extended: nature/ecology death-adjacent stories are OK
    "fossil", "dinosaur", "reef", "coral", "species", "extinct",
    "habitat", "migration", "eruption", "meteor", "asteroid",
    "galaxy", "telescope", "comet", "nebula",
]

def is_kid_safe(title, desc):
    text = (title + " " + desc).lower()
    if any(safe in text for safe in SAFE_OVERRIDES):
        return True
    return not any(bad in text for bad in BLOCKLIST)

# ── RSS fetch + XML parse ──────────────────────────────────────────────────────
def clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()

def fetch_rss(source):
    req = urllib.request.Request(
        source["url"],
        headers={"User-Agent": "Mozilla/5.0 (compatible; KiddieDaily/1.0)"})
    xml_bytes = None
    for attempt in range(3):
        try:
            xml_bytes = urllib.request.urlopen(req, timeout=15, context=ctx).read()
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 2:
                wait = (attempt + 1) * 8
                print(f"    ⏳ {source['name']}: HTTP {e.code}, retry in {wait}s...")
                time.sleep(wait)
            else:
                print(f"    ⚠ {source['name']}: HTTP {e.code}")
                return []
        except Exception as e:
            print(f"    ⚠ {source['name']}: {e}")
            return []
    if xml_bytes is None:
        return []
    try:
        root = ET.fromstring(xml_bytes)
    except Exception as e:
        print(f"    ⚠ {source['name']}: XML parse error: {e}")
        return []

    ATOM  = "http://www.w3.org/2005/Atom"
    RSS1  = "http://purl.org/rss/1.0/"
    DC_NS = "http://purl.org/dc/elements/1.1/"

    def get_field(item, *tags):
        for tag in tags:
            for ns in ("", ATOM, RSS1, DC_NS):
                key = f"{{{ns}}}{tag}" if ns else tag
                el = item.find(key)
                if el is not None and el.text:
                    return el.text.strip()
        return ""

    items = root.findall(".//item")
    if not items:
        items = root.findall(f".//{{{ATOM}}}entry")
    if not items:
        items = root.findall(f".//{{{RSS1}}}item")

    # DW News prefixes like "Germany news:", "Europe news:", "Turkey news:" etc.
    _DW_PREFIX = re.compile(r"^[A-Za-z\s]+\s+news:\s*", re.I)

    stories = []
    for item in items[:25]:
        title = clean(get_field(item, "title"))
        link  = clean(get_field(item, "link", "url"))
        # Atom feeds use <link href="..."/> (attribute, not text) — fall back to href
        if not link:
            for lel in item.findall(f"{{{ATOM}}}link"):
                href = lel.get("href", "")
                if href.startswith("http"):
                    link = href
                    break
        desc  = clean(get_field(item, "description", "summary", "content"))
        pub   = get_field(item, "pubDate", "published", "updated")

        # Strip DW "Germany news: " type prefixes
        if source.get("name") == "DW News":
            title = _DW_PREFIX.sub("", title).strip()

        if not title or not link:
            continue
        if not is_kid_safe(title, desc):
            continue

        stories.append({
            "title": title,
            "link": link,
            "description": desc[:700],
            "pub": pub,
            "source_name": source["name"],
            "source_bias": source["bias"],
            "source_icon": source["icon"],
        })
    return stories

# ── Topic grouping: identify stories multiple sources cover ───────────────────
STOP_WORDS = {"the","a","an","in","on","at","to","for","of","and","or","is","are",
              "was","were","be","has","have","had","will","would","it","this","that",
              "as","by","from","with","its","into","he","she","they","new","says",
              "over","after","amid","amid","before","about","up","out","us","more"}

def keywords(title):
    words = re.sub(r"[^\w\s]", "", title.lower()).split()
    return set(w for w in words if w not in STOP_WORDS and len(w) > 2)

def jaccard(t1, t2):
    w1, w2 = keywords(t1), keywords(t2)
    if not w1 or not w2:
        return 0.0
    return len(w1 & w2) / len(w1 | w2)

SCIENCE_SOURCES = {"NASA", "Science Daily", "Smithsonian", "Science News", "EarthSky", "Live Science", "Phys.org", "MIT News", "New Scientist", "Popular Science", "Space.com", "Ars Technica Science", "Mongabay", "JSTOR Daily", "NASA Earth", "MIT Tech Review", "World History Encyclopedia", "IEEE Spectrum", "The Conversation", "Nautilus", "Archaeology", "Medievalists", "HistoryHit", "Hakai Magazine", "Quanta Magazine", "Discover Magazine", "Mental Floss", "Sci-News", "SciTechDaily", "Berkeley News", "ZME Science", "Wired Science", "Universe Today"}
# Sources written explicitly for kids or general curious audiences — get a ranking boost
KIDS_SOURCES = {"BBC Newsround", "Science News Students", "Good News Network", "Atlas Obscura"}
DEPRIORITIZE_WORDS = [
    "war", "strike", "bomb", "missile", "airstrike", "military",
    "attack", "troops", "soldier", "killed", "dead", "death",
    "iran", "israel", "ukraine", "russia", "hamas", "congress",
    "senate", "republican", "democrat", "trump", "biden", "president",
    "election", "indicted", "arrested", "shooting", "crash",
    # political-regulatory (heavy penalty so non-science replaces them)
    "supreme court", "aoc", "gop", "filibuster", "legislation",
    "firefighter", "firefighters", "police officer", "custody",
    # entertainment/sport-entertainment (low value for kids news)
    "wwe", "tna", "wrestling", "championship belt", "retains the", "smackdown",
    "raw results", "raw recap", "nxt results",
    # professional-sports results/retirements (adult sports industry, not child-development news)
    "test match", "ashes series", "ashes test", "county cricket",
    "t20 series", "t20 match", "t20 cricket", "ipl ",
    "says retiring", "retiring from international", "ends international career",
    "wimbledon final", "wimbledon semi", "wimbledon quarter",
    "premier league", "la liga", "serie a", "ligue 1",
    "formula 1 race", "grand prix result",
    # UK-specific politics (not relevant for US/global families)
    "burnham", "keir starmer", "rishi sunak", "suella braverman",
    "tory party", "labour party", "hs2", "westminster",
    # EU/German-specific politics (DW News source — filter local German politics)
    "bundestag", "bundesrat", "scholz", "friedrich merz", "habeck",
    "spd ", " cdu", " fdp", " afd",
    # Ultra-niche international politics (not relevant for US families)
    "orban", "vucic", "fidesz", "new caledonia", "macron", "french parliament",
    "italian parliament", "spanish parliament", "austrian coalition",
    # Business/finance research (not relevant for kids/parents' child-rearing decisions)
    "sales channel", "supply chain disruption", "quarterly earnings",
    "profit margin", "market share", "shareholder", "stock market", "hedge fund",
    # Shopping/commercial content and lifestyle (product deals, recipes, not educational news)
    "amazon prime", "deal days", "best deals", "sale ends", "buy now", "discount code",
    "prime day", "black friday", "cyber monday", "coupon", "promo code",
    "perfectly cooked", "family cookout", "cookout with", "hot dog recipe", "bbq tips",
    "this week in space podcast", "podcast: episode", "episode —",
    # Personal essays / creative writing / opinion (not factual science/world news)
    "my sci-fi novel", "sci-fi novel", "my novel", "i started my", "why i wrote",
    "when i was", "my journey", "my experience with", "opinion:", "essay:",
    # Fear-mongering / alarmist framing (climate content is fine; panic headlines are not)
    "you should be terrified", "aren't terrified", "should be scared", "be very afraid",
    "doomsday", "apocalypse", "end of the world",
    # Sports lifestyle / how-to (not news, not educational science)
    "got the tennis bug", "got the cycling bug", "got the football bug", "how to play sport",
    # Sports predictions/analysis (journalist opinion, not factual news)
    "predicts world cup", "world cup predictions", "team to beat",
    "sutton predicts", "expert predictions", "power rankings",
    "player ratings", "match ratings", "pundit",
    # World Cup / tournament match results (sports scores, not kids educational news)
    "world cup semi", "world cup final", "world cup quarter",
    "who will england play", "what went wrong for", "top scorer at",
    "will win the world cup", "group stage results",
    # Injury/violence incidents (not educational for kids)
    "people injured", "injured after", "explosion in", "injured in explosion",
    "blast kills", "blast injures", "bombing suspect",
    "earthquake victims", "flood victims", "hurricane victims", "victims shelter",
    "displaced by", "flee their homes", "shelter in place",
    # Crime, legal proceedings, immigration detention (never appropriate for kids)
    "mistrial", "arson case", "arson attack", "vandalism",
    "faces charges", "charged with", "convicted of", "acquitted",
    "detention center", "immigration detention", "deported", "deportation",
    # Election/political process (not kid-educational news)
    "midterm", "primary election", "election results", "primaries", "caucus",
    "live results", "vote count", "ballot count", "exit poll",
    "general election", "runoff election", "polling shows",
    # Partisan US political news (not age-appropriate framing for kids)
    "trump calls", "trump signs", "trump says", "trump admin", "trump's",
    "biden calls", "biden signs", "says trump", "white house says",
    "republican bill", "democrat bill", "gop bill", "housing bill",
    "anti-corruption crackdown", "crackdown in iraq", "corruption case",
    "temporary protected status", "tps program", "protected status",
    "concedes save", "concedes bill", "spending bill", "budget bill vote",
    # International political policy (adult governance topics)
    "devolution plan", "devolution deal", "austerity package", "fiscal plan",
    "renews allegations", "fraud allegations", "corruption allegations",
    "mortgage fraud", "gambling ring", "criminal ring",
    # Court/criminal proceedings scoring (backup to hard-reject)
    "judge delays", "murder trial", "sentencing delayed", "awaiting sentencing",
    "verdict reached", "jury finds", "testifies that",
    # Celebrity content (entertainment not educational news)
    "actress dies", "actor dies", "celebrity dies", "passes away",
    "died of aids", "died of cancer", "died of covid",
    # Adult immigration/asylum policy
    "asylum seekers repay", "refugees told to", "repay asylum",
    # Business/corporate AI content (MIT Tech Review newsletter / enterprise pieces)
    "the download:", "repositioning retail", "enterprise ai",
    "ai for business", "ai strategy for", "corporate ai",
    # Housing/social policy that isn't kids-relevant
    "housing crisis", "van life", "cost of living crisis",
    # Adult health/medical topics not appropriate for kids
    "knee pain", "back pain", "joint pain", "chronic pain",
    "for pms", "menopause", "erectile", "libido", "testosterone therapy",
    "fertility treatment", "ivf", "miscarriage", "abortion pill",
    "hormone therapy", "menstrual",
    # Psychedelic / drug-therapy content (specific compounds → BLOCKLIST; broader term → deprioritize)
    "psychedelic", "ketamine therapy", "mdma therapy",
    "magic mushroom", "psilocybin", "lsd therapy", "ayahuasca",
    "cannabis therapy", "marijuana research", "weed study",
    # Adult disease / clinical research (not age-appropriate framing)
    " hiv ", "hiv enters", "hiv and", "hiv in",
    "alzheimer", "memory loss from",
    "glucosamine", "chemotherapy",
    "infiltrate tumor", "tumors' hostile",
    # News roundups/briefs (supplements commercial filter — lower score before hard-reject)
    "news brief", "morning brief", "evening brief",
    # Tobacco/cigarette industry content (not appropriate for kids context)
    "tobacco company", "tobacco firm", "british american tobacco", "philip morris",
    "cigarette maker", "cigarette company", "vape company", "e-cigarette firm",
    # Gambling / adult entertainment
    "casino", "gambling company", "betting firm", "sports betting",
    # IEEE member-profile / organizational content (not editorial news)
    "senior member", "product lifecycle", "ieee member", "member solves",
    "distinguished lecturer", "fellow elevation",
    # Entertainment tourism / TV filming locations (not educational news)
    "filming locations", "filming location", "film locations", "shot on location",
    "where was filmed", "where they filmed",
    # Adult career / salary content (not age-appropriate)
    "highest-paid job", "highest paid job", "best-paid jobs", "best paid jobs",
    "highest paying", "highest-paying", "top-paying", "top paying",
    "salary by state", "salaries by state", "pay by state",
    "in every state, mapped", "mapped by state", "every state mapped",
    # Sports contract/transfer gossip (adult sports industry news)
    "signs with", "signs for", "transfer fee", "transfer window",
    "contract extension", "agrees deal", "seals deal",
    # Adult self-help / therapy framing (SciTechDaily/ZME repackaged adult psychology)
    "fearing failure", "stop fearing", "fear of failure",
    "people stop fearing", "helps people stop",
    "therapy that helps", "surprising therapy",
    "cognitive behavioral", "cbt therapy",
    # Celebrity royal / fashion content (Mental Floss pop-culture category)
    "princess diana", "revenge dress", "diana's dress",
    "royal family drama", "royal scandal",
    # Celebrity music / pop-culture trivia (not educational for kids)
    "songs you might not know", "songs you didn't know",
    "songs they wrote", "songs written by",
    "wrote for other", "wrote these songs",
    # US partisan Supreme Court / constitutional law (adult political news)
    "scotus", "supreme court spares", "supreme court blocks",
    "supreme court rules", "high court rules",
    # Church-state / curriculum controversy (adult policy debate)
    "bible in schools", "bible required", "required bible",
    "separation of church", "church and state",
    # Adult housing/rental market content
    "salary to rent", "salary needed to rent", "afford rent",
    "average rent", "rental market", "housing affordability",
    # Millennial nostalgia / retro pop-culture (adult demographic, not kids)
    "every millennial", "millennials remember", "millennial played",
    "90s kids remember", "00s kids remember", "millennial classic",
    "forgotten games",
    # Academic lectures / podcast teasers (not news articles)
    "berkeley talks", "berkeley talk:", "philosopher asks",
    "is this our last",
    # Music/entertainment opinion lists (not educational news)
    "musical covers", "covers that are better", "songs that are better",
    "better than the original",
    # Adult beauty/cosmetic content
    "gel nails", "nail art", "manicure", "pedicure", "skin care routine",
    "how to style", "how to wear",
    # US DACA/immigration status (adult policy debate)
    "daca recipients", "daca recipient", "dreamers face",
    "american dream slipping",
    # Adult gender/negotiation social science (adult workplace psychology)
    "prefer negotiating with women", "negotiating with women",
    "even when they don't know", "gender and negotiation",
    # UK NHS healthcare controversy (adult politics)
    "nhs maternity", "maternity scandal", "maternity inquiry",
    "nhs inquiry", "nhs investigation", "nhs crisis",
    "demands nhs", "inquiry demands",
    # Adult sleep/health optimization (not kids science news)
    "sleep optimization", "sleep hacking", "optimal sleep",
    "biohacking", "anti-aging protocol",
    # IEEE organizational events, award ceremonies, training announcements
    "ieee awardee", "epics in ieee", "ieee's awards", "education week events",
    "virtual training course", "ieee rolls out",
    # Career-advice / professional-development articles (off-mission for kids news)
    "technical interview", "what size company", "right for you?",
    "job search tips", "career tips",
    # Surveillance / panopticon concepts (not age-appropriate for KiddieDaily audience)
    "panopticon",
    # Entrepreneur motivational-profile articles
    "the value of resilience", "taught me about resilience",
    # Political opinion framing about corporate/institutional positions (not kids science)
    "climate denial", "legacy of climate",
    # Entertainment ranking listicles (not news, not educational)
    "worst to best", "ranked from worst",
    # Book/movie/game reviews (not news content — use article-style titles only)
    "movie review:", "book review:", "new medieval books:", "game review:",
    # Review headlines structured as "X review: " or "Review: X"
    " review: ", "^review: ",
    # Hakai Magazine recurring photo-feature series (not news articles)
    "one great shot:", "little books with",
    # Adult content framing in science titles (coral/marine biology reproduction)
    "sex lives of",
    # Disaster / tragedy framing that's not appropriate for kids without age-gating
    "mine collapse", "mine explosion", "mine rescue", "miners trapped",
    "rescue efforts continue", "hoping beyond hope", "survivors pulled from",
    "bodies recovered", "toll rises", "death toll",
    # Political sentiment polls / approval surveys (not age-appropriate issue framing)
    "gallup", "approval rating", "favorability rating", "year low", "year high",
    "hits all-time", "confidence in government", "public trust", "american pride",
    "national pride", "voter sentiment", "opinion poll", "poll shows",
    "pew research", "% of americans say", "% say they",
    # Immigration political framing (not age-appropriate issue framing for kids)
    "undocumented migrants", "undocumented immigrants", "anti-immigration",
    "illegal immigration", "immigration crackdown", "migrant caravan",
    "border crossing", "asylum seekers", "deportation order", "expulsion of",
    # Political framing / electoral commentary (covers remaining political gaps)
    "prime minister-in-waiting", "vows to shake up", "shaking up politics",
    "disrupting democracy", "democracy's decline", "disrupting democracy",
    "political comeback", "political turmoil", "opposition leader",
    # Named-author opinion column format (journalist name: topic)
    "mehdi hasan:", "mehdi hasan ",
    # US political figures not already covered (by name → catch specific political stories)
    "hegseth", "pelosi", "mayorkas", "blinken", "yellen", "mcconnell", "schumer",
    "mitch mcconnell", "chuck schumer", "rand paul", "ted cruz", "marco rubio",
    # Politically-charged policy labels
    "obamacare", "aca repeal", "medicaid cut", "snap cut", "food stamp",
    "defense policy board", "national security council",
    # Pride/social-identity advocacy framing (pride celebrations are fine; policy battles not for kids)
    "pride month legislation", "anti-lgbt", "transgender ban", "gender identity bill",
    # Tech-industry lobbying / regulatory affairs (not kids-relevant)
    "antitrust case", "sec charges", "ftc sues", "doj sues", "regulatory fine",
    "billion-dollar fine", "billion fine",
    # Military organization names used as story subjects (not science/world-event framing)
    "pentagon", "nato summit", "nato alliance",
    "department of defense", "defense secretary", "joint chiefs",
    # Military personnel loss framing (not appropriate for kids)
    "missing soldier", "missing sailor", "missing marine", "missing airman",
    "lost at sea", "killed in action", "fallen soldier",
    # Geopolitical sanctions / diplomatic confrontation
    "sanctions imposed", "sanctions lifted", "economic sanctions",
    "expelled the ambassador", "summoned the ambassador",
    # Prison / incarceration stories
    "prison sentence", "sentenced to prison", "life sentence",
    "death row", "death penalty", "capital punishment",
    # Extremist / terror content
    "terrorist attack", "terror plot", "extremist group",
    "jihad", "isis", "al-qaeda", "boko haram",
    # Horoscope / astrology content (pseudoscience, not educational)
    "horoscope", "weekly horoscope", "free will astrology", "astrology forecast",
    "your stars this week", "zodiac forecast", "sun sign",
    # Entertainment movie/TV ranking lists (not news)
    "ranked by rotten tomatoes", "rotten tomatoes score", "movies ranked",
    "all 13 star wars", "all 10 star wars", "every star wars film",
    "ranked worst to", "films ranked", "episodes ranked",
    # Fast food commercial preference content (not educational)
    "favorite fast food chain", "fast food chains mapped", "best fast food",
    "america's favorite restaurant", "favorite fast food",
    # Adult cancer-warning health alerts (medical, not kids science)
    "colorectal cancer", "colon cancer symptoms", "colorectal symptoms",
    "cancer symptoms to watch", "surgeons warn", "don't ignore these symptoms",
    # Adult housing/mortgage market content
    "mortgage rates frustrate", "homes harder to sell", "harder to sell",
    "housing market cooling", "homes sitting longer", "real estate slowdown",
    "affordability crisis",
    # Combat sports / violent sports results (not age-appropriate for kids)
    "ufc results", "boxing results", "mma results", "knockout win", "knocked out",
    "unanimous decision", "split decision", "title defense", "fight recap",
    # Alcohol and spirits content
    "craft beer", "craft ipa", "best whiskey", "best bourbon", "cocktail recipe",
    "wine tasting", "beer review", "spirits review", "distillery tour",
    # Pregnancy / baby product parenting content
    "third trimester", "postpartum", "baby formula", "best stroller",
    "maternity leave", "newborn sleep", "breastfeeding", "diaper",
    # Crypto / NFT / adult investing content
    "bitcoin price", "ethereum price", "crypto market", "nft mint",
    "index fund", "roth ira", "401k", "dividend yield", "hedge fund",
    "stock market crash", "portfolio rebalancing",
    # Obituary / tribute format (not celebrity deaths — separate)
    "in memoriam", "one year since", "a life remembered", "legacy of",
    "years later: the faces", "remembering the victims",
    # Adult FIRE / early retirement personal finance content
    "retired at", "retire at", "retired early", "early retirement",
    "financial independence", "fire movement", "f.i.r.e.", "financially free",
    "packed lunches and retired", "we retired at", "how we retired",
    "quit our jobs and retired",
    # NPR/BBC author spotlight format ("Firstname Lastname on [topic]")
    " on spotlighting", " on writing", " on crafting", " on telling",
    " on creating his", " on creating her", " on creating their",
    "author's journey", "in conversation with", "talks about his novel",
    "talks about her novel", "talks about their novel",
    # Fiction novel/book announcement (not news)
    "new novel", "debut novel", "new memoir", "new book by",
    "book excerpt", "excerpt from",
]

# Max absolute bias for world news articles (highly partisan sources get skipped)
MAX_WORLD_NEWS_BIAS = 0.6

def ranking_score(group):
    n = len(group)
    has_science = any(s["source_name"] in SCIENCE_SOURCES for s in group)
    has_kids   = any(s["source_name"] in KIDS_SOURCES for s in group)
    bias_penalty = abs(sum(s["source_bias"] for s in group) / n)
    combined_text = " ".join(s["title"].lower() for s in group)
    heavy_news = sum(1 for w in DEPRIORITIZE_WORDS if w in combined_text)
    return (
        (5 if has_science else 0)  # science sources get big boost
        + (3 if has_kids else 0)   # kid-targeted sources get priority
        + n * 2                    # more corroborating sources = better
        - heavy_news * 3           # political/military words = penalty
        - bias_penalty             # extreme bias = small penalty
    )

def group_stories(stories):
    groups = []
    used = set()
    for i, s in enumerate(stories):
        if i in used:
            continue
        group = [s]
        used.add(i)
        for j, other in enumerate(stories):
            if j in used or j == i:
                continue
            if jaccard(s["title"], other["title"]) > 0.18:
                group.append(other)
                used.add(j)
        groups.append(group)
    groups.sort(key=ranking_score, reverse=True)
    return groups

# ── Bias + source-agreement scoring ──────────────────────────────────────────
def score_group(group):
    biases = [s["source_bias"] for s in group]
    bias_avg = sum(biases) / len(biases)
    n = len(set(s["source_name"] for s in group))
    agreement_pct = min(99, round((n / len(SOURCES)) * 250))  # scaled: 4/8 sources → ~100%
    return {
        "bias_avg": round(bias_avg, 2),
        "n_sources": n,
        "agreement_pct": agreement_pct,
        "sources": [{"name": s["source_name"], "bias": s["source_bias"], "icon": s["source_icon"]} for s in group],
    }

# ── Bias bar + agreement badge HTML ──────────────────────────────────────────
BIAS_CSS = """
.kd-bias-box{background:#f7fafc;border:1px solid #e2e8f0;border-radius:10px;padding:16px 20px;margin:22px 0 18px;font-family:system-ui,sans-serif;font-size:14px}
.kd-bias-hdr{font-size:11px;text-transform:uppercase;letter-spacing:1.2px;color:#718096;font-weight:600;margin-bottom:10px}
.kd-bias-row{display:flex;align-items:center;gap:10px;margin:6px 0 4px}
.kd-bias-lbl{font-size:12px;font-weight:700;width:32px}
.kd-bias-lbl.l{color:#3182ce;text-align:right}
.kd-bias-lbl.r{color:#e53e3e}
.kd-bias-track{flex:1;height:10px;background:linear-gradient(to right,#3182ce 0%,#805ad5 50%,#e53e3e 100%);border-radius:5px;position:relative}
.kd-bias-dot{position:absolute;top:-5px;width:20px;height:20px;background:#1a1a1a;border-radius:50%;border:3px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.3);transform:translateX(-50%)}
.kd-bias-tag{font-size:13px;color:#4a5568;margin-left:6px}
.kd-chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 8px}
.kd-chip{padding:3px 10px;border-radius:12px;font-size:12px;white-space:nowrap}
.kd-chip.L{background:#ebf8ff;color:#2b6cb0}
.kd-chip.C{background:#f0fff4;color:#276749}
.kd-chip.R{background:#fff5f5;color:#c53030}
.kd-agree-row{display:flex;align-items:center;gap:10px;margin-top:6px}
.kd-badge{padding:4px 12px;border-radius:12px;font-size:13px;font-weight:700}
.kd-badge-sci{background:#d1fae5;color:#065f46}
.kd-badge-news{background:#dbeafe;color:#1e40af}
.badge-hi{background:#c6f6d5;color:#22543d}
.badge-med{background:#fefcbf;color:#744210}
.badge-lo{background:#fed7d7;color:#742a2a}
.kd-agree-note{font-size:12px;color:#718096}
"""

def bias_bar_html(score):
    bias = score["bias_avg"]
    pct = max(5, min(95, round((bias + 2) / 4 * 100)))

    bias_label = ("Far Left" if bias <= -1.2 else "Leans Left" if bias <= -0.4
                  else "Center-Left" if bias <= -0.15 else "Center" if bias <= 0.15
                  else "Center-Right" if bias <= 0.4 else "Leans Right" if bias <= 1.2
                  else "Far Right")

    chips = []
    for src in score["sources"]:
        b = src["bias"]
        cls = "L" if b <= -0.2 else ("R" if b >= 0.2 else "C")
        chips.append(f'<span class="kd-chip {cls}">{src["icon"]} {src["name"]}</span>')

    ap = score["agreement_pct"]
    badge_cls = "badge-hi" if ap >= 65 else ("badge-med" if ap >= 35 else "badge-lo")
    n = score["n_sources"]

    return f"""<div class="kd-bias-box">
<div class="kd-bias-hdr">📊 Source Analysis — KiddieDaily Editorial</div>
<div class="kd-bias-row">
  <span class="kd-bias-lbl l">Left</span>
  <div class="kd-bias-track"><div class="kd-bias-dot" style="left:{pct}%"></div></div>
  <span class="kd-bias-lbl r">Right</span>
  <strong class="kd-bias-tag">{bias_label}</strong>
</div>
<div class="kd-chips">{"".join(chips)}</div>
<div class="kd-agree-row">
  <span class="kd-badge {badge_cls}">{ap}% source agreement</span>
  <span class="kd-agree-note">Covered by {n} independent source{"s" if n!=1 else ""}</span>
</div>
</div>
<p style="font-size:12px;color:#a0aec0;margin-top:-12px;font-family:system-ui,sans-serif">
Bias ratings based on <em>AllSides</em> + <em>Ad Fontes Media</em>. Agreement % = sources covering this story.
Always read multiple sources and think critically.
</p>"""

# ── Anthropic Haiku rewrite (optional) ────────────────────────────────────────
def rewrite_for_kids(title, description):
    if not ANTHROPIC_KEY:
        return None
    prompt = f"""You are a writer for KiddieDaily, a fact-checked daily news site for kids ages 8-14 and their parents.

Original headline: {title}
Original summary: {description}

Rewrite this as a short kid-friendly article. Return ONLY the article, no meta-commentary.

FORMAT (follow exactly):
[Kid-friendly headline — exciting, accurate, max 12 words]

[Lede — 2 vivid sentences that hook a curious kid. Start with what happened.]

## What Happened
[3-4 simple sentences: the core facts, explained like you're talking to a smart 10-year-old.]

## Why It Matters
[2-3 sentences: real-world impact. Connect to something kids care about — animals, space, health, discovery.]

## Think About This
[One open question for family discussion. Starts with "What do you think..." or "Why do you think..."]

RULES:
- No violence, war, politics, or adult content. Skip if unavoidable.
- Use vivid, concrete language. Avoid jargon.
- Keep total length under 200 words.
- Tone: warm, curious, slightly excited — like a science teacher who loves their subject."""

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 900,
            "messages": [{"role": "user", "content": prompt}]
        }).encode(),
        headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        method="POST")
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=30, context=ctx).read())
        return r.get("content", [{}])[0].get("text", "").strip()
    except Exception as e:
        print(f"    ⚠ Anthropic API: {e}")
        return None

# ── Article body builders ─────────────────────────────────────────────────────
SKIP_PARA_WORDS = [
    "cookie", "subscribe", "newsletter", "javascript", "sign up",
    "advertisement", "click here", "read more", "follow us",
    "privacy policy", "terms of use", "all rights reserved",
    "copyright", "©", "skip to", "share this", "email address",
    "by clicking", "you agree", "logged in", "create account",
    "already a subscriber", "to continue reading", "paywall",
    "enable javascript", "browser does not support", "reload the page",
    "get the latest", "breaking news", "follow on", "download the app",
]

# Dateline pattern — "CITY, STATE (SOURCE) — " at start of text
_DATELINE_RE = re.compile(
    r"^[A-Z][A-Z ,'\-]{2,40}(?:\([^)]{2,20}\))?\s*[—\-]{1,3}\s*", re.UNICODE
)

def _clean_lede(text):
    """Strip news datelines and boilerplate from the opening of a paragraph."""
    text = text.strip()
    # Remove datelines like "WASHINGTON (AP) — " or "NEW YORK — "
    text = _DATELINE_RE.sub("", text)
    # Remove byline openers like "By Staff Writer · "
    text = re.sub(r"^By [A-Z][a-zA-Z .'\-]+ [·|•]\s*", "", text)
    # Normalize HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&#39;", "'").replace("&quot;", '"').replace("&nbsp;", " ")
    return text.strip()

def fetch_article_text(url, fallback):
    """Fetch full article text from source URL; return cleaned paragraphs or fallback."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        req = urllib.request.Request(url, headers=headers)
        raw = urllib.request.urlopen(req, timeout=7, context=ctx).read().decode("utf-8", errors="replace")
        # Strip scripts, styles, nav, footer, aside, header, form, figure captions
        raw = re.sub(
            r"<(script|style|nav|footer|aside|header|form|figcaption|noscript)[^>]*>.*?</\1>",
            "", raw, flags=re.DOTALL | re.IGNORECASE
        )
        # Extract <p> content
        paras = re.findall(r"<p[^>]*>(.*?)</p>", raw, re.DOTALL | re.IGNORECASE)
        paras = [re.sub(r"<[^>]+>", "", p).strip() for p in paras]
        paras = [re.sub(r"\s+", " ", p) for p in paras]
        paras = [
            _clean_lede(p) if idx == 0 else p
            for idx, p in enumerate(paras)
            if len(p) > 50
            and not any(w in p.lower() for w in SKIP_PARA_WORDS)
        ]
        if len(paras) >= 2:
            return " ".join(paras[:9])
    except Exception:
        pass
    # Clean the fallback description too
    clean_fb = re.sub(r"<[^>]+>", "", fallback or "").strip()
    clean_fb = re.sub(r"\s+", " ", clean_fb)
    return _clean_lede(clean_fb) if clean_fb else (fallback or "")


def body_from_rss(group):
    rep = group[0]
    # Try to fetch full text; fall back to RSS description
    full_text = fetch_article_text(rep["link"], rep["description"])

    sentences = [_clean_lede(s) if i == 0 else s
                 for i, s in enumerate(
                     s.strip() for s in re.split(r"(?<=[.!?])\s+", full_text)
                     if len(s.strip()) > 25
                 )]

    # Detect science article by checking group sources against SCIENCE_SOURCES
    is_science = any(s["source_name"] in SCIENCE_SOURCES for s in group)
    h2_mid  = "What scientists found" if is_science else "What happened"
    h2_late = "Why it matters for kids"

    # Lede = first sentence only (dateline already stripped by _clean_lede above)
    lede = sentences[0] if sentences else _clean_lede(full_text[:220])

    # Build structured paragraphs from remaining sentences (groups of 2-3)
    body_sents = sentences[1:]  # everything after the lede sentence
    html = [f'<p class="lede">{lede}</p>']

    i = 0
    para_index = 0  # counts paragraphs emitted so we can insert h2s at the right spots
    while i < len(body_sents):
        # Insert h2 before the paragraph that starts at original sentence index 3 (0-based)
        # sentence index 3 = body_sents index 2 (lede was sentence 0)
        orig_sent_idx = i + 1  # +1 because body_sents starts at sentence[1]
        if orig_sent_idx == 3 and len(sentences) >= 6:
            html.append(f"<h2>{h2_mid}</h2>")
        if orig_sent_idx == 6 and len(sentences) >= 9:
            html.append(f"<h2>{h2_late}</h2>")
        chunk = body_sents[i:i + 3]
        html.append(f"<p>{' '.join(chunk)}</p>")
        i += 3
        para_index += 1

    # Other-source perspective (multi-source stories)
    others = [s for s in group[1:3] if s["description"] and s["description"][:80] != rep["description"][:80]]
    if others:
        other_text = fetch_article_text(others[0]["link"], others[0]["description"])
        other_sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", other_text) if len(s.strip()) > 25]
        other_lede = " ".join(other_sents[:3]) if other_sents else others[0]["description"][:400]
        html.append(
            f"<h2>How {others[0]['source_icon']} {others[0]['source_name']} Covers It</h2>"
            f"<p>{other_lede}</p>"
        )

    html.append(
        "<h2>Think About This</h2>"
        "<p>What questions does this story raise for you? Talk with your family: "
        "Why does this news matter? Who is affected? What might happen next? "
        "Is there anything you can do?</p>"
    )
    return rep["title"], "".join(html)

def body_from_api(original_title, text):
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return original_title, f"<p>{text}</p>"

    new_title = lines[0]
    html_parts = []
    lede_done = False
    buf = []

    for ln in lines[1:]:
        if ln.startswith("##") or ln.startswith("#"):
            if buf:
                content = " ".join(buf)
                tag = 'p class="lede"' if not lede_done else "p"
                html_parts.append(f"<{tag}>{content}</p>")
                lede_done = True
                buf = []
            html_parts.append(f"<h2>{ln.lstrip('#').strip()}</h2>")
        else:
            buf.append(ln)

    if buf:
        content = " ".join(buf)
        tag = 'p class="lede"' if not lede_done else "p"
        html_parts.append(f"<{tag}>{content}</p>")

    return new_title, "".join(html_parts)

# ── Page template ─────────────────────────────────────────────────────────────
CSS = '''<style>
*{box-sizing:border-box}html{font-family:Georgia,"Times New Roman",serif;color:#1a1a1a;background:#faf8f3;line-height:1.6}
body{margin:0;font-size:17px}a{color:#1a4d80;text-decoration:none}a:hover{text-decoration:underline}
header.kd{background:#1a4d80;color:#fff;padding:12px 24px}
header.kd .inner{max-width:980px;margin:0 auto;display:flex;flex-wrap:wrap;align-items:center;gap:18px}
header.kd .logo{font-weight:700;font-size:22px;color:#fff;font-family:Georgia,serif}
header.kd .logo small{display:block;font-size:11px;font-weight:400;letter-spacing:2px;color:#cbd5e0;text-transform:uppercase}
header.kd nav{display:flex;flex-wrap:wrap;gap:18px;flex:1;justify-content:flex-end}
header.kd nav a{color:#fff;font-size:15px;font-family:system-ui,sans-serif}
header.kd nav a:hover{color:#ffd700}
.pz-cta{background:#ffd700;color:#1a1a1a;padding:6px 14px;border-radius:6px;font-weight:600;font-size:14px;font-family:system-ui,sans-serif}
main{max-width:780px;margin:0 auto;padding:32px 24px 64px}
h1{font-size:36px;line-height:1.2;margin:8px 0 16px}
h2{font-size:26px;margin:32px 0 12px;color:#2d3748;border-bottom:1px solid #e5e7eb;padding-bottom:6px}
p{margin:0 0 16px}.lede{font-size:20px;color:#4a5568;margin-bottom:24px;font-style:italic}
.byline{font-size:14px;color:#718096;margin:0 0 24px}
.sources{background:#f7fafc;border-left:4px solid #1a4d80;padding:14px 18px;margin:18px 0;font-size:15px}
.sources h4{margin:0 0 6px;color:#1a4d80;font-size:14px;letter-spacing:1px;text-transform:uppercase;font-family:system-ui,sans-serif}
.sources ul{margin:0;padding-left:22px}
footer.kd{background:#1a202c;color:#cbd5e0;padding:36px 24px;margin-top:48px;font-family:system-ui,sans-serif}
footer.kd .inner{max-width:980px;margin:0 auto;display:flex;flex-wrap:wrap;gap:32px}
footer.kd h4{color:#fff;margin:0 0 10px;font-size:13px;letter-spacing:1.5px;text-transform:uppercase}
footer.kd a{color:#cbd5e0;display:block;padding:3px 0;font-size:14px}
.kd-card-excerpt{font-size:13px;color:#4a5568;margin:4px 0 6px;line-height:1.4;font-family:system-ui,sans-serif;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.kd-bias-text{font-size:10px;color:#718096;margin-left:6px}
.kd-skip{position:absolute;top:-48px;left:0;background:#1a4d80;color:#fff;padding:8px 16px;font-size:14px;font-family:system-ui,sans-serif;z-index:200;text-decoration:none;border-radius:0 0 6px 0;transition:top .15s}.kd-skip:focus{top:0;outline:3px solid #ffd700}
.kd-ham{display:none;background:none;border:none;cursor:pointer;color:#fff;font-size:24px;line-height:1;padding:4px 8px}
@media(max-width:640px){.kd-ham{display:flex;align-items:center;margin-left:auto;order:2}header.kd nav{display:none;order:3;width:100%;flex-direction:column;gap:0;padding:6px 0 8px;justify-content:flex-start}header.kd nav.open{display:flex}header.kd nav a{padding:12px 0;font-size:16px;border-top:1px solid rgba(255,255,255,.12);min-height:44px;display:flex;align-items:center}.pz-cta{width:fit-content}main{padding:20px 16px 48px}}
#kd-prog{position:fixed;top:0;left:0;height:3px;width:0%;background:linear-gradient(90deg,#1a4d80,#38b2ac);z-index:9999;transition:width .08s linear;pointer-events:none}
@media(prefers-color-scheme:dark){html{background:#0f1117;color:#e2e8f0}header.kd{background:#0d2d54}a{color:#90cdf4}.byline,.kd-card-excerpt,.kd-bias-text{color:#a0aec0}.sources{background:#1a202c;border-left-color:#4a5568}footer.kd{background:#070c14}.kd-sc{background:#1a202c;border-color:#2d3748}.kd-sc h3 a{color:#90cdf4}h2{color:#a0c4ff;border-color:#2d3748}#search,#cat-search,#today-search{background:#1a202c;color:#e2e8f0;border-color:#4a5568}main{background:#0f1117}}
@media print{header.kd,footer.kd,#kd-prog,.kd-skip,button,.kd-ham{display:none!important}main{max-width:100%!important;padding:0!important;margin:0!important}a{color:#000!important}h1,h2,h3{break-after:avoid}p{orphans:3;widows:3}.sources{border:1px solid #000;background:none!important}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{transition:none!important;animation:none!important}}
''' + BIAS_CSS + '</style>\n<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22%3E%3Ctext y=%22.9em%22 font-size=%2290%22%3E&#x1f4f0;%3C/text%3E%3C/svg%3E"><link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#1a4d80"><meta name="theme-color" content="#0d2d54" media="(prefers-color-scheme:dark)"><script>if("serviceWorker"in navigator)navigator.serviceWorker.register("/sw.js");</script>'

HEADER = """<a href="#main" class="kd-skip">Skip to content</a><header class="kd"><div class="inner">
<a href="/" class="logo">KiddieDaily<small>News for Families</small></a>
<button class="kd-ham" onclick="this.closest('header').querySelector('nav').classList.toggle('open')" aria-label="Open menu">&#9776;</button>
<nav><a href="/news/today.html">Today</a><a href="/news/">Kid News</a><a href="/search.html">Search</a><a href="/fact-check/">Fact Check</a>
<a href="/games/">Games</a><a href="/draw/">Draw</a><a href="/wonder/">Wonder</a><a href="/saved.html">Saved</a><a href="/about.html">About</a><a href="/parents/" class="pz-cta">For Parents</a></nav>
</div></header>"""

FOOTER = """<footer class="kd"><div class="inner">
<div style="flex:1;min-width:200px"><h4>KiddieDaily</h4>
<p style="margin:0;font-size:14px;color:#cbd5e0">Curated daily news for families with research-backed fact checks.</p></div>
<div><h4>Read</h4><a href="/news/today.html">Today's News</a><a href="/news/">Kid News</a><a href="/digest/latest.html">Daily Digest</a>
<a href="/parents/">For Parents</a><a href="/fact-check/">Fact Check</a><a href="/games/">Games</a><a href="/draw/">Draw the News</a></div>
<div><h4>Account</h4><a href="/saved.html">Saved Stories</a><a href="/parents/">For Parents</a><a href="/subscribe/">Subscribe</a><a href="/about.html">About</a>
<a href="/contact.html">Contact</a></div>
<div><h4>Legal</h4><a href="/privacy.html">Privacy</a><a href="/terms.html">Terms</a></div>
<div><h4>Explore &amp; Play</h4><a href="/wonder/">Explore by Wonder</a><a href="/hello/">Maya's Hello</a><a href="/news-word/">News Word</a><a href="/news-numbers/">By the Numbers</a><a href="/time-traveler/">Time Traveler</a></div>
<div><h4>Our Network</h4><a href="https://kiddiewordle.com" rel="noopener">KiddieWordle</a>
<a href="https://kiddiesketch.com" rel="noopener">KiddieSketch</a>
<a href="https://kiddiego.com" rel="noopener">KiddieGo</a></div>
</div>
<div style="text-align:center;font-size:13px;color:#a0aec0;margin-top:24px">
&copy; 2026 KiddieDaily &middot; A Legacy Bridge Alliance Group family project<br>
<span style="font-size:11px;opacity:.6">Press <kbd style="background:#1a3660;border:1px solid #2d4f80;border-radius:3px;padding:1px 5px;font-family:monospace">/</kbd> to search</span></div>
</footer>
<script>document.addEventListener('keydown',function(e){if(e.key==='/'&&document.activeElement.tagName!=='INPUT'&&document.activeElement.tagName!=='TEXTAREA'){var s=document.getElementById('kd-search-input')||document.getElementById('search');if(s){e.preventDefault();s.focus();}else{window.location='/search.html';}}});
(function(){try{
  var KEY='kd_streak',LAST='kd_last';
  var today=new Date().toISOString().slice(0,10);
  var last=localStorage.getItem(LAST);
  var streak=parseInt(localStorage.getItem(KEY)||'0',10);
  if(!last){streak=1;}
  else if(last<today){
    var yest=new Date(Date.now()-864e5).toISOString().slice(0,10);
    streak=(last===yest?streak+1:1);
  }
  localStorage.setItem(KEY,streak);localStorage.setItem(LAST,today);
  if(streak>=2){
    var b=document.createElement('div');
    b.innerHTML='&#128293;&nbsp;'+streak+'-day streak!';
    b.style.cssText='position:fixed;bottom:16px;right:16px;z-index:9998;background:#fef3c7;color:#92400e;border:1px solid #fde68a;padding:6px 14px;border-radius:20px;font-size:13px;font-weight:700;font-family:system-ui,sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.12);pointer-events:none;opacity:1';
    document.body.appendChild(b);
    setTimeout(function(){b.style.transition='opacity 1.5s';b.style.opacity='0';setTimeout(function(){if(b.parentNode)b.parentNode.removeChild(b);},1500);},3500);
  }
}catch(e){}})();
(function(){try{var n=JSON.parse(localStorage.getItem('kd_saved')||'[]').length;if(n>0){var links=document.querySelectorAll('a[href="/saved.html"]');links.forEach(function(l){l.textContent='🔖 Saved ('+n+')';});}}catch(e){}})();</script>"""

def make_slug(title, date_str):
    # Normalize accented characters (ñ→n, é→e, etc.) so the URL path stays ASCII-safe
    normalized = unicodedata.normalize("NFKD", title.lower()).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w\s-]", "", normalized)
    slug = re.sub(r"\s+", "-", slug.strip())[:50].rstrip("-")
    return f"news/{date_str}-{slug}.html"

def reading_time(html_text):
    words = len(re.sub(r"<[^>]+>", " ", html_text).split())
    mins = max(1, round(words / 200))
    return f"{mins} min read"

def reading_level(html_text):
    """Return a simple grade-level label (Ages 8-10, Ages 10-12, Ages 12+) using avg word length."""
    plain = re.sub(r"<[^>]+>", " ", html_text)
    words = [w for w in plain.split() if w.isalpha()]
    if not words:
        return "Ages 8+"
    avg_len = sum(len(w) for w in words) / len(words)
    if avg_len < 5.0:
        return "Ages 8–10"
    elif avg_len < 6.5:
        return "Ages 10–12"
    else:
        return "Ages 12+"

def parent_discussion_guide(title, is_science):
    """Return an HTML parent discussion guide for an article."""
    # Extract 1-2 meaningful topic words from the title for question prompts
    stop = {"about", "their", "these", "those", "would", "could", "which", "where",
            "there", "after", "other", "first", "world", "using", "study", "finds",
            "found", "shows", "says", "that", "have", "with", "from", "this", "will"}
    words = [w for w in re.sub(r"[^\w\s]", "", title.lower()).split()
             if len(w) > 3 and w not in stop]
    topic = " ".join(words[:2]) if len(words) >= 2 else (words[0] if words else "this topic")

    if is_science:
        bullets = [
            (f"<strong>Ask your child:</strong> &ldquo;What do you think scientists discovered about <em>{topic}</em>? "
             "What part surprised you most?&rdquo;"),
            ("<strong>Explore together:</strong> Search for &ldquo;" + topic + "&rdquo; on NASA Kids&#x2019; Club, "
             "DK Find Out, or National Geographic Kids for more kid-friendly facts."),
            ("<strong>Critical thinking:</strong> Science findings can change as more research is done. Ask: "
             "&ldquo;How would scientists test this? What would prove them wrong?&rdquo;"),
        ]
        icon, color, bg, border = "🔬", "#065f46", "#f0fff4", "#9ae6b4"
    else:
        bullets = [
            (f"<strong>Ask your child:</strong> &ldquo;Why do you think people care about <em>{topic}</em>? "
             "How might this affect families like ours?&rdquo;"),
            ("<strong>Compare sources:</strong> The bias rating above shows how this outlet leans. Try finding "
             "one more source that covers the same story. Do they agree? What&rsquo;s different?"),
            ("<strong>Media literacy:</strong> Ask: &ldquo;What facts does this story give us? "
             "What opinions does it include? Who is speaking, and why might they say this?&rdquo;"),
        ]
        icon, color, bg, border = "🗞️", "#1e40af", "#eff6ff", "#93c5fd"

    rows = "".join(
        f'<li style="margin:8px 0;line-height:1.55;font-size:14px;color:#2d3748">{b}</li>'
        for b in bullets
    )
    return (
        f'<div style="background:{bg};border:1px solid {border};border-radius:10px;'
        f'padding:18px 22px;margin:22px 0;font-family:system-ui,sans-serif">'
        f'<div style="font-size:11px;font-weight:700;color:{color};text-transform:uppercase;'
        f'letter-spacing:1.1px;margin-bottom:12px">{icon} Parent discussion guide</div>'
        f'<ul style="margin:0;padding:0 0 0 18px">{rows}</ul>'
        f'<p style="font-size:11px;color:#a0aec0;margin:12px 0 0">KiddieDaily is built for families — '
        f'balanced sources, no agenda, no ads. Always read the original source and think for yourself.</p>'
        f'</div>'
    )


def build_page(title, body_html, bias_html, score, group, slug, today, cats=None):
    n = score["n_sources"]
    url = f"https://kiddiedaily.com/{slug}"
    # og:description — clean text from RSS summary (strip HTML tags)
    raw_desc = group[0].get("description", "") if group else ""
    og_desc = re.sub(r"<[^>]+>", "", raw_desc).strip()[:160] or title[:160]
    is_sci_page = any(s.get("source_name", "") in SCIENCE_SOURCES for s in group)
    og_image = "https://kiddiedaily.com/og-science.svg" if is_sci_page else "https://kiddiedaily.com/og-news.svg"
    _art_section = "Science" if is_sci_page else "World News"
    _art_section_url = "https://kiddiedaily.com/news/science.html" if is_sci_page else "https://kiddiedaily.com/news/world.html"
    jsonld = json.dumps([
        {
            "@context": "https://schema.org", "@type": "NewsArticle",
            "headline": title,
            "description": og_desc,
            "image": og_image,
            "url": url,
            "inLanguage": "en-US",
            "isAccessibleForFree": True,
            "articleSection": _art_section,
            "keywords": cats or [],
            "author": {"@type": "Organization", "name": "KiddieDaily Editors"},
            "publisher": {"@type": "Organization", "name": "KiddieDaily", "url": "https://kiddiedaily.com"},
            "datePublished": today, "dateModified": today,
            "mainEntityOfPage": {"@type": "WebPage", "@id": url}
        },
        {
            "@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "KiddieDaily", "item": "https://kiddiedaily.com"},
                {"@type": "ListItem", "position": 2, "name": "News", "item": "https://kiddiedaily.com/news/"},
                {"@type": "ListItem", "position": 3, "name": _art_section, "item": _art_section_url},
                {"@type": "ListItem", "position": 4, "name": title, "item": url},
            ]
        }
    ])

    source_items = "".join(
        f'<li>{s["source_icon"]} <a href="{s["link"]}" rel="noopener nofollow" target="_blank">'
        f'{s["source_name"]}: {s["title"][:75]}{"..." if len(s["title"])>75 else ""}</a></li>'
        for s in group
    )
    # Google Fact Check Explorer link — lets parents quickly search for claims
    fc_query = urllib.parse.quote(title[:80])
    fact_check_url = f"https://toolbox.google.com/factcheck/explorer/search/{fc_query}"

    # Multiple perspectives block — shows how each outlet framed the story
    def _perspectives_html(group, n):
        if n < 2:
            return ""
        rows = []
        for s in group:
            b = s["source_bias"]
            lean = ("Left" if b <= -0.4 else ("Right" if b >= 0.4 else "Center"))
            lean_color = "#2b6cb0" if lean == "Left" else ("#c53030" if lean == "Right" else "#276749")
            headline = s["title"][:100] + ("…" if len(s["title"]) > 100 else "")
            rows.append(
                f'<div style="padding:10px 14px;border-left:3px solid {lean_color};margin:6px 0;background:#fafafa;border-radius:0 6px 6px 0">'
                f'<span style="font-size:11px;font-weight:700;color:{lean_color};text-transform:uppercase;letter-spacing:.8px">{lean}</span>'
                f' <span style="font-size:11px;color:#718096">&mdash; {s["source_icon"]} {s["source_name"]}</span><br>'
                f'<span style="font-size:14px;color:#2d3748">{headline}</span>'
                f'</div>'
            )
        return (
            '<div style="background:#fff8e1;border:1px solid #fde68a;border-radius:10px;padding:16px 20px;margin:18px 0;font-family:system-ui,sans-serif">'
            '<div style="font-size:11px;font-weight:700;color:#92400e;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px">'
            '&#127919; Multiple perspectives — how outlets framed this story</div>'
            + "".join(rows) +
            '<p style="font-size:11px;color:#a0aec0;margin:8px 0 0">Reading multiple sources helps you spot framing differences. '
            'Neither left- nor right-leaning outlets are always wrong — or always right.</p>'
            '</div>'
        )

    perspectives_html = _perspectives_html(group, n)
    is_sci = any(s["source_name"] in SCIENCE_SOURCES for s in group)
    guide_html = parent_discussion_guide(title, is_sci)

    rt = reading_time(body_html)
    rl = reading_level(body_html)
    from datetime import datetime as _dt
    _friendly_today = _dt.strptime(today, "%Y-%m-%d").strftime("%b %d, %Y").replace(" 0", " ")
    cat_label = "Science" if is_sci else "World News"
    cat_url   = "/news/science.html" if is_sci else "/news/world.html"
    _SUBCAT_META = {
        "space":       ("🚀", "Space",       "/news/space.html",       "#ede9fe", "#5b21b6"),
        "animals":     ("🐾", "Animals",     "/news/animals.html",     "#fef3c7", "#92400e"),
        "history":     ("🏛", "History",     "/news/history.html",     "#fce7f3", "#9d174d"),
        "environment": ("🌿", "Environment", "/news/environment.html", "#dcfce7", "#166534"),
        "technology":  ("💻", "Technology",  "/news/technology.html",  "#e0e7ff", "#3730a3"),
    }
    # "Explore the Topic" — category-matched kid-safe external resources
    _EXPLORE_LINKS = {
        "space":       [("🚀 NASA Kids", "https://www.nasa.gov/stem/forstudents/k-4/index.html"),
                        ("🌌 Astronomy for Kids", "https://astronomy.com/get-involved/activities"),
                        ("📡 Space.com for Students", "https://www.space.com/science-astronomy")],
        "animals":     [("🐾 Nat Geo Kids: Animals", "https://kids.nationalgeographic.com/animals/"),
                        ("🦁 WWF Kids", "https://www.worldwildlife.org/species"),
                        ("🐘 Smithsonian Zoos", "https://nationalzoo.si.edu/animals")],
        "history":     [("📜 Britannica Kids", "https://kids.britannica.com/"),
                        ("🏛 Smithsonian Learning Lab", "https://learninglab.si.edu/"),
                        ("🗺️ World History Encyclopedia", "https://www.worldhistory.org/")],
        "environment": [("🌿 NASA Climate Kids", "https://climatekids.nasa.gov/"),
                        ("🌎 EPA Students", "https://www.epa.gov/students"),
                        ("🌊 NOAA Ocean Service Education", "https://oceanservice.noaa.gov/education/")],
        "technology":  [("💻 Code.org", "https://code.org/learn"),
                        ("🤖 CS4Kids", "https://www.cs4fn.org/"),
                        ("⚡ IEEE Try Engineering", "https://tryengineering.org/")],
        "science":     [("🔬 Science News for Students", "https://www.snexplores.org/"),
                        ("🧬 Khan Academy Science", "https://www.khanacademy.org/science"),
                        ("🏛 Smithsonian Science Ed.", "https://ssec.si.edu/")],
        "world":       [("🌍 Nat Geo Kids: World", "https://kids.nationalgeographic.com/explore/"),
                        ("📰 TIME for Kids", "https://www.timeforkids.com/"),
                        ("🌐 DK Find Out!", "https://www.dkfindout.com/us/")],
    }
    _explore_cats = ([c for c in (cats or []) if c in _EXPLORE_LINKS]
                     or (["science"] if is_sci else ["world"]))
    _explore_links = []
    for _ec in _explore_cats[:2]:
        for _link in _EXPLORE_LINKS.get(_ec, []):
            if _link not in _explore_links:
                _explore_links.append(_link)
    if not _explore_links:
        _explore_links = _EXPLORE_LINKS["science" if is_sci else "world"]
    _explore_links = _explore_links[:3]
    explore_html = (
        '<div style="margin:20px 0;padding:14px 18px;background:#fafafa;border:1px solid #e2e8f0;border-radius:10px;font-family:system-ui,sans-serif">'
        '<div style="font-size:11px;font-weight:700;color:#4a5568;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px">🔭 Explore the topic further</div>'
        '<div style="display:flex;flex-wrap:wrap;gap:8px">'
        + "".join(
            f'<a href="{url}" rel="noopener noreferrer" target="_blank" '
            f'style="display:inline-block;background:#fff;border:1px solid #e2e8f0;'
            f'border-radius:8px;padding:7px 13px;font-size:13px;color:#1a4d80;text-decoration:none;'
            f'font-weight:500">{label}</a>'
            for label, url in _explore_links
        )
        + '</div></div>'
    )

    json_cats = json.dumps(cats or [])

    subcat_pills = ""
    if cats:
        subcats = [c for c in cats if c in _SUBCAT_META]
        if subcats:
            pill_html = "".join(
                f'<a href="{_SUBCAT_META[c][2]}" style="display:inline-flex;align-items:center;gap:4px;'
                f'background:{_SUBCAT_META[c][3]};color:{_SUBCAT_META[c][4]};border-radius:20px;'
                f'padding:3px 12px;font-size:12px;font-weight:600;text-decoration:none;font-family:system-ui,sans-serif">'
                f'{_SUBCAT_META[c][0]} {_SUBCAT_META[c][1]}</a>'
                for c in subcats
            )
            subcat_pills = f'<div style="display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 12px">{pill_html}</div>'
    body = f"""<nav aria-label="Breadcrumb" style="font-size:12px;color:#718096;font-family:system-ui,sans-serif;margin-bottom:10px">
<a href="/" style="color:#718096">KiddieDaily</a> ›
<a href="/news/" style="color:#718096">News</a> ›
<a href="{cat_url}" style="color:#1a4d80;font-weight:600">{cat_label}</a>
</nav>{subcat_pills}
<p class="byline">By KiddieDaily Editors &middot; <time datetime="{today}">{_friendly_today}</time> &middot; {rt} &middot; <span title="Estimated reading level">{rl}</span> &middot; {n} source{"s" if n!=1 else ""}</p>
<h1>{title}</h1>
{bias_html}
{perspectives_html}
{body_html}
{guide_html}
{explore_html}
<div style="margin:16px 0 24px;padding:14px 18px;background:#fffbeb;border:1px solid #fde68a;border-radius:10px;font-family:system-ui,sans-serif;display:flex;align-items:center;gap:14px;flex-wrap:wrap">
<div style="font-size:26px">🎮</div>
<div style="flex:1;min-width:160px">
<strong style="font-size:14px;display:block;color:#92400e;margin-bottom:2px">Ready to test your knowledge?</strong>
<span style="font-size:13px;color:#a16207">Play today's science quiz and word scramble on the Games page.</span>
</div>
<a href="/games/" style="background:#d97706;color:#fff;padding:8px 16px;border-radius:6px;font-size:13px;text-decoration:none;white-space:nowrap;font-weight:600">Play now &rarr;</a>
</div>
<div class="sources"><h4>Original Sources</h4><ul>{source_items}</ul></div>
<p style="margin-top:16px;padding:10px 14px;background:#f0fff4;border:1px solid #c6f6d5;border-radius:8px;font-size:13px">
&#128269; <strong>Want to verify this story?</strong>
<a href="{fact_check_url}" rel="noopener nofollow" target="_blank" style="color:#065f46">Check it on Google Fact Check Explorer &rarr;</a>
</p>
<div style="margin:24px 0;padding:16px 20px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:10px;display:flex;align-items:center;gap:16px;flex-wrap:wrap">
<div style="font-size:28px">&#128240;</div>
<div style="flex:1">
<strong style="font-size:15px;display:block;color:#0c4a6e;margin-bottom:2px">Get today's digest</strong>
<span style="font-size:13px;color:#075985">All of today's kid-safe stories in one parent-friendly roundup — with bias ratings.</span>
</div>
<a href="/digest/latest.html" style="background:#0c4a6e;color:#fff;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;white-space:nowrap;font-family:system-ui,sans-serif">Read digest &rarr;</a>
</div>
<div id="kd-related" style="margin:24px 0;display:none">
<h3 style="font-family:system-ui,sans-serif;font-size:16px;color:#1a4d80;margin:0 0 12px">&#128218; More stories you might like</h3>
<div id="kd-related-cards" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px"></div>
</div>
<script>(function(){{
  var thisCats={json_cats};var thisSlug='{slug}';
  fetch('/data/kd-articles.json').then(function(r){{return r.json();}}).then(function(data){{
    var scored=[];
    data.forEach(function(a){{
      if(a.slug===thisSlug)return;
      var shared=0;if(a.cats&&thisCats){{a.cats.forEach(function(c){{if(thisCats.indexOf(c)>=0)shared++;}});}}
      if(shared>0)scored.push({{a:a,score:shared+(Math.random()*0.4)}});
    }});
    scored.sort(function(x,y){{return y.score-x.score;}});
    var picks=scored.slice(0,4);
    if(!picks.length)return;
    var ctr=document.getElementById('kd-related-cards');
    picks.forEach(function(p){{
      var a=p.a;
      var el=document.createElement('a');
      el.href='/news/'+a.slug+'.html';
      el.style.cssText='display:block;padding:12px 14px;background:#f7fafc;border:1px solid #e2e8f0;border-radius:8px;text-decoration:none;color:#1a202c;font-family:system-ui,sans-serif;transition:background 0.15s';
      el.onmouseover=function(){{this.style.background='#edf2f7';}};
      el.onmouseout=function(){{this.style.background='#f7fafc';}};
      var dateStr=a.date||'';
      el.innerHTML='<div style="font-size:11px;color:#718096;margin-bottom:5px">'+dateStr+'</div><div style="font-size:13px;font-weight:600;line-height:1.45;color:#1a4d80">'+a.title+'</div>';
      ctr.appendChild(el);
    }});
    document.getElementById('kd-related').style.display='block';
  }}).catch(function(){{}});
}})();</script>
<p><em>More stories: <a href="/news/">Kid News</a> &middot; <a href="/news/archive.html">Archive</a> &middot; <a href="/fact-check/">Fact Check</a></em></p>
<div style="margin-top:20px;display:flex;gap:10px;flex-wrap:wrap">
<button onclick="if(navigator.share){{navigator.share({{title:document.title,url:location.href}})}}else{{navigator.clipboard.writeText(location.href);this.textContent='Link copied!';setTimeout(()=>this.textContent='Copy link',2000)}}" style="background:#1a4d80;color:#fff;border:none;padding:8px 18px;border-radius:6px;cursor:pointer;font-size:14px">Share this story</button>
<button id="kd-save-btn" onclick="(function(){{var K='kd_saved',s='{slug}',saved=JSON.parse(localStorage.getItem(K)||'[]'),idx=saved.indexOf(s);if(idx>=0){{saved.splice(idx,1);}}else{{saved.push(s);}}localStorage.setItem(K,JSON.stringify(saved));var b=document.getElementById('kd-save-btn');if(idx>=0){{b.style.background='#f7fafc';b.style.color='#1a4d80';b.textContent='🔖 Save';}}else{{b.style.background='#d1fae5';b.style.color='#065f46';b.textContent='✓ Saved';}}}})()" style="background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80;padding:8px 18px;border-radius:6px;cursor:pointer;font-size:14px">🔖 Save</button>
<a href="/news/" style="background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80;padding:8px 18px;border-radius:6px;font-size:14px;text-decoration:none">&larr; All news</a>
<a href="/feed.xml" style="background:#f7fafc;color:#718096;border:1px solid #e2e8f0;padding:8px 18px;border-radius:6px;font-size:14px;text-decoration:none">RSS feed</a>
</div>
<script>(function(){{var K='kd_saved',s='{slug}',saved=JSON.parse(localStorage.getItem(K)||'[]'),b=document.getElementById('kd-save-btn');if(b&&saved.indexOf(s)>=0){{b.style.background='#d1fae5';b.style.color='#065f46';b.textContent='✓ Saved';}}}})()</script>"""

    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta name="description" content="{og_desc}">
<link rel="canonical" href="{url}">
<title>{title} — KiddieDaily</title>
<meta property="og:type" content="article"><meta property="og:title" content="{title}">
<meta property="og:url" content="{url}"><meta property="og:site_name" content="KiddieDaily">
<meta property="og:description" content="{og_desc}">
<meta property="og:image" content="{og_image}">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{og_desc}">
<meta name="twitter:image" content="{og_image}">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22%3E%3Ctext y=%22.9em%22 font-size=%2290%22%3E&#x1f4f0;%3C/text%3E%3C/svg%3E">
<script type="application/ld+json">{jsonld}</script>
{CSS}</head><body><div id="kd-prog"></div>{HEADER}<main id="main">{body}</main>{FOOTER}
<script>
(function(){{
  const SLUG="{slug}";
  const PAGE_CATS=new Set({json.dumps([c for c in (cats or []) if c not in ("science","world")])});
  const TITLE_WORDS=new Set("{title}".toLowerCase().replace(/[^\\w\\s]/g,"").split(/\\s+/).filter(w=>w.length>3&&!["that","this","with","from","have","were","they","more"].includes(w)));
  const MO=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  function fmtDate(d){{var p=d?d.split('-'):[];return p.length===3?MO[parseInt(p[1])-1]+' '+parseInt(p[2])+', '+p[0]:d||'';}}
  const CCLR={{"space":"#ede9fe;color:#5b21b6","animals":"#fef3c7;color:#92400e","history":"#fce7f3;color:#9d174d","environment":"#dcfce7;color:#166534","technology":"#e0e7ff;color:#3730a3"}};
  fetch("/data/kd-articles.json").then(r=>r.json()).then(articles=>{{
    const scored=articles.filter(a=>a.slug!==SLUG).map(a=>{{
      const w=new Set(a.title.toLowerCase().replace(/[^\\w\\s]/g,"").split(/\\s+/).filter(x=>x.length>3));
      const overlap=[...TITLE_WORDS].filter(x=>w.has(x)).length;
      const ac=new Set((a.cats||[]).filter(c=>c!=="science"&&c!=="world"));
      const catBoost=[...PAGE_CATS].filter(c=>ac.has(c)).length*0.8;
      return{{...a,score:overlap+catBoost+(a.is_science?0.3:0)}};
    }}).sort((a,b)=>b.score-a.score).slice(0,3).filter(a=>a.score>0);
    if(!scored.length)return;
    const box=document.createElement("div");
    box.style.cssText="max-width:780px;margin:0 auto;padding:0 24px 48px;font-family:system-ui,sans-serif";
    box.innerHTML="<h2 style='font-size:18px;color:#2d3748;border-bottom:1px solid #e5e7eb;padding-bottom:6px;margin-bottom:12px'>Related stories</h2>"
      +scored.map(a=>{{
        const subcats=(a.cats||[]).filter(c=>c!=="science"&&c!=="world").slice(0,2);
        const pills=subcats.map(c=>{{const s=CCLR[c]||"#f3f4f6;color:#374151";return`<span style="font-size:10px;background:${{s}};padding:1px 7px;border-radius:20px;font-weight:600;margin-left:4px">${{c}}</span>`;}}).join("");
        return`<div style='margin:8px 0;padding:10px 14px;background:#fff;border:1px solid #e5e7eb;border-radius:8px'>
        <span style='font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;background:${{a.is_science?"#d1fae5":"#dbeafe"}};color:${{a.is_science?"#065f46":"#1e40af"}};padding:2px 7px;border-radius:20px'>${{a.is_science?"Science":"World News"}}</span>${{pills}}
        <a href="/${{a.slug}}" style='display:block;color:#1a4d80;font-weight:600;margin:5px 0 2px;font-size:15px'>${{a.title}}</a>
        ${{a.description?`<p style='font-size:13px;color:#4a5568;margin:3px 0 4px;line-height:1.4'>${{a.description.length>120?a.description.slice(0,120)+"…":a.description}}</p>`:""}}
        <span style='font-size:11px;color:#a0aec0'>${{fmtDate(a.date)}}</span>
        </div>`;
      }}).join("");
    const ft=document.querySelector('footer.kd');
    if(ft)ft.parentNode.insertBefore(box,ft);else document.body.appendChild(box);
  }}).catch(()=>{{}});
  window.addEventListener('scroll',function(){{
    var d=document.documentElement;
    var pct=100*d.scrollTop/((d.scrollHeight-d.clientHeight)||1);
    document.getElementById('kd-prog').style.width=Math.min(100,pct)+'%';
  }},{{passive:true}});
}})();
</script>
</body></html>"""

# ── Manifest: tracks pushed slugs to avoid duplicates ─────────────────────────
def load_manifest():
    r = gh("GET", f"/repos/{REPO}/contents/data/kd-scraped-manifest.json")
    if r.get("_err") or not r.get("sha"):
        return {"pushed_slugs": [], "pushed_titles": [], "articles": []}
    content = r.get("content", "")
    if not content:
        # File > 1MB: Contents API omits inline content. Fall back to Blob API.
        blob = gh("GET", f"/repos/{REPO}/git/blobs/{r['sha']}")
        content = blob.get("content", "")
    if not content:
        return {"pushed_slugs": [], "pushed_titles": [], "articles": []}
    try:
        m = json.loads(base64.b64decode(content).decode("utf-8"))
    except Exception:
        return {"pushed_slugs": [], "pushed_titles": [], "articles": []}

    # Migrate: if pushed_slugs exist but articles list is missing, create stubs
    if m.get("pushed_slugs") and not m.get("articles"):
        m["articles"] = []
        titles = m.get("pushed_titles", [])
        for i, slug in enumerate(m["pushed_slugs"]):
            title = titles[i] if i < len(titles) else "Article"
            date_match = re.search(r"\d{4}-\d{2}-\d{2}", slug)
            m["articles"].append({
                "slug": slug,
                "title": title,
                "display_title": title,
                "date": date_match.group() if date_match else "2026-06-26",
                "n_sources": 1,
                "bias_avg": 0.0,
                "agreement_pct": 30,
                "is_science": any(w in slug for w in ["nasa", "science", "space", "animal"]),
            })
        print(f"    (migrated {len(m['articles'])} legacy articles to new manifest format)")

    return m

def save_manifest(manifest):
    # Trim descriptions to 200 chars to keep manifest compact (full text lives in kd-articles.json)
    slim_articles = []
    for a in manifest.get("articles", []):
        s = dict(a)
        if len(s.get("description", "")) > 200:
            s["description"] = s["description"][:200]
        slim_articles.append(s)
    slim = {**manifest, "articles": slim_articles}
    upload("data/kd-scraped-manifest.json",
           json.dumps(slim, ensure_ascii=False),
           "Update scraped articles manifest")

# ── news/index.html — fully generated dynamic hub ─────────────────────────────
# Historical / educational framing — deep-past content (archaeology, paleontology, ancient &
# medieval history) legitimately uses words like "famine", "plague", "died", "war" that the
# world-reject filter targets in CURRENT news. A title with clear historical framing is exempted
# from world-reject so kids' history/science stays. Deliberately excludes bare "history"/"historic"
# (those show up in current political news, e.g. "cites a history professor").
_HISTORICAL_RE = re.compile(
    r"\b\d[\d,]*\s+years?\s+ago\b|\bcenturies\s+ago\b|\bmillennia\b"
    r"|\bancient\b|\bmedieval\b|\bprehistoric\b|\bantiquity\b"
    r"|\b(?:bronze|iron|stone|ice)\s+age\b"
    r"|\bneanderthals?\b|\bhunter.?gatherers?\b|\bpharaoh\w*|\bmummies|\bmummy\b"
    r"|\barchaeolog\w+|\bexcavat\w+|\bunearth\w+"
    r"|\bfossil\w*|\bdinosaur\w*|\bmammoth\w*|\btrilobite\w*"
    r"|\bgreat\s+famine\b|\bblack\s+death\b"
    r"|\b\d{3,4}\s*(?:BCE?|AD)\b|\bmillion\s+years?\b|\bcentury\b",
    re.I,
)


def retro_purge_filtered(manifest):
    """Self-healing corpus: re-apply the current hard-reject filters to every
    already-published article on every run. A filter patch thus cleans up past
    slip-throughs automatically — no manual purge cycle. Purged entries stay in
    pushed_slugs/pushed_titles so they are never re-scraped; their HTML pages
    are deleted from the repo and they drop out of every regenerated index."""
    kept, purged = [], []
    for a in manifest.get("articles", []):
        titles = {a.get("title", ""), a.get("display_title", "")}
        titles.discard("")
        bad = any(
            _ADULT_TITLE_RE.search(t) or _COMMERCIAL_TITLE_RE.search(t)
            or (_WORLD_NEWS_REJECT_RE.search(t) and not _HISTORICAL_RE.search(t))
            for t in titles
        )
        (purged if bad else kept).append(a)
    if not purged:
        return 0
    manifest["articles"] = kept
    for a in purged:
        print(f"    ✂ {a.get('date','')} | {(a.get('display_title') or a.get('title',''))[:70]}")
        slug = a.get("slug", "")
        if not slug:
            continue
        r = gh("GET", f"/repos/{REPO}/contents/{slug}?ref={ACTIVE_BRANCH}")
        if isinstance(r, dict) and r.get("sha") and not r.get("_err"):
            gh("DELETE", f"/repos/{REPO}/contents/{slug}",
               {"message": "[scraper] Retro-purge filtered article page",
                "sha": r["sha"], "branch": ACTIVE_BRANCH})
            time.sleep(0.3)
    return len(purged)


def generate_news_index_page(manifest):
    articles = manifest.get("articles", [])
    total    = len(articles)

    CAT_CARDS = [
        ("🔬", "Science",     "news/science.html",     "#d1fae5", "#065f46", "science"),
        ("🌍", "World",       "news/world.html",       "#dbeafe", "#1e40af", "world"),
        ("🚀", "Space",       "news/space.html",       "#ede9fe", "#5b21b6", "space"),
        ("🐾", "Animals",     "news/animals.html",     "#fef3c7", "#92400e", "animals"),
        ("🏛", "History",     "news/history.html",     "#fce7f3", "#9d174d", "history"),
        ("🌿", "Environment", "news/environment.html", "#dcfce7", "#166534", "environment"),
        ("💻", "Technology",  "news/technology.html",  "#e0e7ff", "#3730a3", "technology"),
    ]
    cat_grid = "".join(
        f'<a href="/{path}" class="ni-cat" style="background:{bg};color:{fg}">'
        f'<span class="ni-icon">{icon}</span>{label}'
        f'<span id="ni-c-{key}" class="ni-cat-count" style="font-size:11px;opacity:.7;font-weight:400"></span></a>'
        for icon, label, path, bg, fg, key in CAT_CARDS
    )

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kid News Hub — KiddieDaily</title>
<meta name="description" content="Browse all {total} kid-safe, bias-rated articles across Science, Space, Animals, History, Environment, Technology and World News.">
<link rel="canonical" href="https://kiddiedaily.com/news/">
{CSS}
<style>
.ni-cat-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px;margin:18px 0 28px}}
.ni-cat{{display:flex;flex-direction:column;align-items:center;padding:14px 8px;border-radius:12px;font-weight:700;font-size:13px;text-align:center;text-decoration:none;gap:6px;transition:opacity .15s}}
.ni-cat:hover{{opacity:.82;text-decoration:none}}
.ni-icon{{font-size:28px}}
#ni-search{{width:100%;padding:10px 14px;border:1.5px solid #dde4ef;border-radius:8px;font-size:15px;margin-bottom:16px;font-family:inherit}}
.ni-card{{padding:14px 0;border-bottom:1px solid #e5e7eb}}
.ni-card a{{font-size:15px;font-weight:600;color:#1a4d80;display:block;margin:4px 0;line-height:1.4}}
.ni-card a:hover{{text-decoration:underline}}
.ni-card-meta{{font-size:12px;color:#718096}}
.ni-badge{{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.6px;padding:2px 7px;border-radius:20px;margin-right:5px;text-transform:uppercase}}
.ni-badge-sci{{background:#d1fae5;color:#065f46}}
.ni-badge-news{{background:#dbeafe;color:#1e40af}}
.ni-badge-cat{{background:#f3f4f6;color:#374151}}
.ni-more{{display:block;text-align:center;padding:11px;background:#f0f4f8;border:none;border-radius:8px;cursor:pointer;font-size:14px;font-weight:600;color:#1a4d80;width:100%;margin-top:16px}}
.ni-count{{font-size:13px;color:#718096;margin-bottom:12px}}
</style>
</head><body><div id="kd-prog"></div>
{HEADER}
<main id="main" style="max-width:760px;margin:0 auto;padding:20px 16px">
<h1 style="font-size:1.5em;color:#1a4d80;margin-bottom:4px">Kid News Hub</h1>
<p style="color:#718096;margin:0 0 6px;font-size:14px">{total} articles — bias-rated, kid-safe, updated daily</p>

<div class="ni-cat-grid">{cat_grid}</div>

<h2 style="font-size:1.15em;color:#1a4d80;border-bottom:2px solid #ffd700;padding-bottom:6px;margin-bottom:14px">All Articles</h2>
<input type="text" id="ni-search" placeholder="Search all articles..." aria-label="Search articles">
<div id="ni-featured" style="display:none;margin-bottom:20px"></div>
<div id="ni-count" class="ni-count"></div>
<div id="ni-list"></div>
<button id="ni-more" class="ni-more" onclick="niMore()">Load more</button>
</main>
{FOOTER}
<script>
(function(){{
  var PAGE=20,arts=[],off=0,q='',filt=[];
  var MO=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  var TODAY_STR=new Date().toISOString().slice(0,10);
  function fmtDate(d){{var p=d?d.split('-'):[];return p.length===3?MO[parseInt(p[1])-1]+' '+parseInt(p[2])+', '+p[0]:d||'';}}
  function blbl(b){{return b<=-1.2?'Far Left':b<=-0.4?'Leans Left':b<=-.15?'Ctr-Left':b<=.15?'Center':b<=.4?'Ctr-Right':b<=1.2?'Leans Right':'Far Right';}}
  function card(a){{
    var sci=a.is_science,bc=sci?'ni-badge-sci':'ni-badge-news',bl=sci?'Science':'World';
    var cats=(a.cats||[]).filter(function(c){{return c!=='science'&&c!=='world';}});
    var tags=cats.slice(0,2).map(function(c){{return'<span class="ni-badge ni-badge-cat">'+c+'</span>';}}).join('');
    var ex=a.description?a.description.slice(0,110)+(a.description.length>110?'…':''):'';
    var n=a.n_sources||1;
    var multi=n>1?'<span style="font-size:10px;background:#fff8e1;color:#92400e;border:1px solid #fde68a;padding:1px 6px;border-radius:20px;font-weight:700;margin-left:5px">'+n+' outlets</span>':'';
    var newBadge=a.date===TODAY_STR?'<span style="font-size:10px;background:#dc2626;color:#fff;padding:1px 6px;border-radius:20px;font-weight:700;margin-left:5px">NEW</span>':'';
    return'<div class="ni-card"><span class="ni-badge '+bc+'">'+bl+'</span>'+tags+multi+newBadge+'<a href="/'+a.slug+'">'+a.title+'</a>'+(ex?'<p style="margin:3px 0 5px;font-size:12px;color:#4a5568;line-height:1.4">'+ex+'</p>':'')+'<div class="ni-card-meta">'+fmtDate(a.date)+' &middot; '+blbl(a.bias_avg)+'</div></div>';
  }}
  function applyFilter(){{filt=q?arts.filter(function(a){{return((a.title||'')+' '+(a.description||'')).toLowerCase().indexOf(q)>=0;}}):arts;}}
  function render(){{
    var list=document.getElementById('ni-list'),btn=document.getElementById('ni-more'),cnt=document.getElementById('ni-count');
    if(!off)list.innerHTML='';
    var chunk=filt.slice(off,off+PAGE);
    list.innerHTML+=chunk.map(card).join('');
    off+=PAGE;
    var rem=filt.length-off;
    btn.style.display=rem>0?'block':'none';
    if(rem>0)btn.textContent='Load '+Math.min(PAGE,rem)+' more ('+rem+' remaining)';
    cnt.textContent='Showing '+Math.min(off,filt.length)+' of '+filt.length+' articles';
  }}
  window.niMore=function(){{render();}};
  document.getElementById('ni-search').addEventListener('input',function(e){{
    q=e.target.value.toLowerCase().trim();off=0;applyFilter();render();
  }});
  fetch('/data/kd-articles.json').then(function(r){{return r.json();}}).then(function(data){{
    arts=data;
    // Dynamic category counts
    var cc={{science:0,world:0,space:0,animals:0,history:0,environment:0,technology:0}};
    arts.forEach(function(a){{
      if(a.is_science)cc.science++;else cc.world++;
      (a.cats||[]).forEach(function(c){{if(c!=='science'&&c!=='world'&&cc.hasOwnProperty(c))cc[c]++;}});
    }});
    Object.keys(cc).forEach(function(k){{var el=document.getElementById('ni-c-'+k);if(el)el.textContent=cc[k];}});
    // Featured top story from today (or most recent)
    var todayStr=new Date().toISOString().slice(0,10);
    var pool=arts.filter(function(a){{return a.date===todayStr;}});
    if(!pool.length)pool=arts.slice(0,50);
    var top=pool.sort(function(a,b){{return(b.n_sources||1)-(a.n_sources||1);}})[0];
    if(top&&(top.n_sources||1)>1){{
      var fe=document.getElementById('ni-featured');
      fe.style.display='block';
      fe.innerHTML='<h2 style="font-size:1.05em;color:#1a4d80;border-bottom:2px solid #ffd700;padding-bottom:4px;margin-bottom:10px">&#11088; Top Story Today</h2>'
        +'<div style="background:#fffbeb;border:1px solid #fef3c7;border-radius:10px;padding:16px">'
        +'<a href="/'+top.slug+'" style="font-size:17px;font-weight:700;color:#1a4d80;display:block;margin-bottom:6px">'+top.title+'</a>'
        +(top.description?'<p style="font-size:14px;color:#4a5568;margin:0 0 8px;line-height:1.4">'+(top.description.length>160?top.description.slice(0,160)+'…':top.description)+'</p>':'')
        +'<span style="font-size:12px;color:#92400e;background:#fef3c7;padding:2px 8px;border-radius:20px;font-weight:600">&#x1f4f0; '+(top.n_sources||1)+' outlets covering this story</span>'
        +'</div>';
    }}
    applyFilter();render();
  }});
  window.addEventListener('scroll',function(){{
    var d=document.documentElement;
    document.getElementById('kd-prog').style.width=Math.min(100,100*d.scrollTop/((d.scrollHeight-d.clientHeight)||1))+'%';
  }},{{passive:true}});
}})();
</script>
</body></html>"""
    upload("news/index.html", page, f"[scraper] news/index — dynamic hub, {total} articles")

# ── GitHub Actions workflow (self-deployed to kiddiedaily repo) ───────────────
WORKFLOW_YAML = """\
name: KiddieDaily Daily News Scraper

on:
  schedule:
    - cron: '0 10 * * *'    # 6am ET — morning update
    - cron: '0 16 * * *'    # noon ET — midday update
    - cron: '0 22 * * *'    # 6pm ET — evening update
  workflow_dispatch:          # manual trigger for testing

jobs:
  scrape-and-push:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Run KiddieDaily news scraper
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: python scrape_and_push.py
"""

PR_REVIEW_YAML = """\
name: Content PR Review Agent

on:
  pull_request:
    branches: [main]
    types: [opened, synchronize, reopened]

jobs:
  # Stage 1: validate script syntax
  review-script:
    name: "Stage 1 — Script Syntax Check"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.head_ref }}
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Python syntax check
        run: |
          python -m py_compile scrape_and_push.py
          echo "✓ scrape_and_push.py syntax OK"

  # Stage 2: validate generated content
  review-content:
    name: "Stage 2 — Content Validator"
    runs-on: ubuntu-latest
    needs: review-script
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.head_ref }}
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Validate HTML files (DOCTYPE + KiddieDaily header)
        run: |
          python - <<'EOF'
          import os, sys
          fail = 0
          for root, _, files in os.walk('.'):
              if '.git' in root:
                  continue
              for f in files:
                  if not f.endswith('.html'):
                      continue
                  path = os.path.join(root, f)
                  text = open(path, encoding='utf-8', errors='ignore').read()
                  if '<!DOCTYPE html>' not in text and '<!doctype html>' not in text.lower():
                      print(f'FAIL missing DOCTYPE: {path}')
                      fail += 1
          print(f'HTML check: {fail} failures')
          sys.exit(fail > 0)
          EOF
      - name: Validate articles JSON index
        run: |
          python - <<'EOF'
          import json, sys
          try:
              data = json.load(open('data/kd-articles.json'))
              assert len(data) > 0, "Empty articles JSON"
              required = {'slug', 'title', 'date', 'is_science'}
              for item in data[:3]:
                  missing = required - set(item.keys())
                  assert not missing, f"Missing fields {missing} in {item.get('slug','?')}"
              print(f"✓ {len(data)} articles in index, schema OK")
          except Exception as e:
              print(f"FAIL: {e}")
              sys.exit(1)
          EOF
      - name: Validate RSS feed
        run: |
          python - <<'EOF'
          import xml.etree.ElementTree as ET, sys
          try:
              tree = ET.parse('feed.xml')
              items = tree.findall('.//{http://www.w3.org/2005/Atom}entry') or \
                      tree.findall('.//item')
              print(f"✓ RSS feed has {len(items)} items")
          except Exception as e:
              print(f"FAIL RSS: {e}")
              sys.exit(1)
          EOF

  # Stage 3: validate sitemap
  review-sitemap:
    name: "Stage 3 — Sitemap & Coverage Check"
    runs-on: ubuntu-latest
    needs: review-content
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.head_ref }}
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Validate sitemap
        run: |
          python - <<'EOF'
          import xml.etree.ElementTree as ET, sys
          tree = ET.parse('sitemap.xml')
          ns = 'http://www.sitemaps.org/schemas/sitemap/0.9'
          urls = [u.text for u in tree.findall(f'.//{{{ns}}}loc')]
          required = ['/', '/news/', '/news/archive.html', '/feed.xml',
                      '/news/science.html', '/search.html', '/digest/latest.html']
          missing = [r for r in required if not any(r in u for u in urls)]
          if missing:
              print(f"FAIL sitemap missing: {missing}")
              sys.exit(1)
          print(f"✓ Sitemap has {len(urls)} URLs, all required pages present")
          EOF
      - name: Coverage report
        run: |
          python - <<'EOF'
          import os, json
          cats = {'news': 0, 'digest': 0, 'search': 0}
          for root, _, files in os.walk('.'):
              if '.git' in root: continue
              for f in files:
                  if f.endswith('.html'):
                      k = root.split(os.sep)[1] if len(root.split(os.sep)) > 1 else 'root'
                      cats[k] = cats.get(k, 0) + 1
          print("Coverage:", json.dumps(cats, indent=2))
          articles = json.load(open('data/kd-articles.json'))
          print(f"✓ Total articles: {len(articles)}")
          EOF
"""

CODEOWNERS_FILE = """\
# KiddieDaily CODEOWNERS
# Automated content PRs (content/daily-news-*) have no human reviewer requirement.
# All source code + workflow changes route to the repo owner.
* @Omtatsat101
scrape_and_push.py @Omtatsat101
.github/ @Omtatsat101
"""

PR_TEMPLATE_MD = """\
## Summary
<!-- What changed? Automated content update or manual fix? -->

## Type
- [ ] Automated content update (daily news scraper)
- [ ] Scraper improvement
- [ ] Workflow / CI update
- [ ] Bug fix
- [ ] Other

## Checklist
- [ ] Python syntax check passes (`python -m py_compile scrape_and_push.py`)
- [ ] Articles JSON valid (`data/kd-articles.json` schema OK)
- [ ] Sitemap includes all required URLs
- [ ] No secrets or credentials included
- [ ] CI review stages all pass
"""

# ── Sitemap ───────────────────────────────────────────────────────────────────
STATIC_URLS = [
    "/", "/news/", "/parents/", "/fact-check/", "/games/",
    "/search.html",
    "/news/galaxy-far-far-away.html",
    "/news/water-filter-invention.html",
    "/news/sea-turtles-comeback.html",
    "/parents/screen-time-balance.html",
    "/parents/back-to-school-anxiety.html",
    "/parents/read-aloud-after-8.html",
    "/fact-check/tylenol-kids-brains.html",
    "/fact-check/social-media-teen-depression.html",
    "/games/index.html",
    "/draw/",
    "/wonder/", "/hello/", "/news-word/", "/news-numbers/", "/time-traveler/",
    "/about.html", "/privacy.html", "/terms.html", "/contact.html", "/status.html",
    "/subscribe/",
    "/feed.xml", "/news/archive.html", "/news/today.html",
    "/news/science.html", "/news/world.html",
    "/news/space.html", "/news/animals.html", "/news/history.html", "/news/environment.html", "/news/technology.html",
    "/digest/latest.html",
    "/digest/weekly.html",
]

def update_sitemap(pushed_slugs, manifest=None):
    BASE_URL = "https://kiddiedaily.com"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Collect all URLs
    urls = list(STATIC_URLS)
    for slug in pushed_slugs:
        # slug is already a full repo path like "news/2026-06-26-title.html"
        url = f"/{slug}" if not slug.startswith("/") else slug
        if url not in urls:
            urls.append(url)

    # Add digest pages for each unique date in the manifest
    if manifest:
        digest_dates = set()
        for a in manifest.get("articles", []):
            d = a.get("date", "")
            if d:
                digest_dates.add(d)
        for d in sorted(digest_dates):
            url = f"/digest/{d}.html"
            if url not in urls:
                urls.append(url)
        if digest_dates:
            urls_set = set(urls)
            if "/digest/latest.html" not in urls_set:
                urls.append("/digest/latest.html")

    _DAILY = {"/", "/news/", "/news/today.html", "/news/archive.html", "/digest/latest.html"}
    _WEEKLY = {"/search.html", "/parents/", "/fact-check/", "/games/", "/subscribe/",
               "/news/science.html", "/news/world.html", "/news/space.html",
               "/news/animals.html", "/news/history.html", "/news/environment.html", "/news/technology.html"}
    def _fp(u):
        if u in _DAILY: return "daily", "1.0"
        if u in _WEEKLY or u.startswith("/digest/"): return "weekly", "0.8"
        if u.startswith("/news/"): return "monthly", "0.6"
        return "monthly", "0.4"

    xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        freq, prio = _fp(u)
        xml_lines.append(f"  <url>")
        xml_lines.append(f"    <loc>{BASE_URL}{u}</loc>")
        xml_lines.append(f"    <lastmod>{today}</lastmod>")
        xml_lines.append(f"    <changefreq>{freq}</changefreq>")
        xml_lines.append(f"    <priority>{prio}</priority>")
        xml_lines.append(f"  </url>")
    xml_lines.append("</urlset>")
    sitemap_content = "\n".join(xml_lines) + "\n"

    upload("sitemap.xml", sitemap_content, f"[scraper] Rebuild sitemap with {len(pushed_slugs)} scraped articles")
    print(f"  Sitemap rebuilt — {len(urls)} URLs total")


# ── Homepage widget ───────────────────────────────────────────────────────────
HOMEPAGE_START = "<!-- HOMEPAGE_NEWS_START -->"
HOMEPAGE_END   = "<!-- HOMEPAGE_NEWS_END -->"

def update_homepage(manifest):
    articles = manifest.get("articles", [])
    if not articles:
        return

    r = gh("GET", f"/repos/{REPO}/contents/index.html")
    if r.get("_err"):
        print(f"    ⚠ Could not fetch index.html: {r}")
        return

    html = base64.b64decode(r["content"]).decode("utf-8")
    latest = sorted(articles, key=lambda x: x.get("date", ""), reverse=True)[:3]

    cards = []
    for a in latest:
        slug  = a["slug"]
        title = a.get("display_title", a.get("title", ""))[:90]
        date  = a.get("date", "")
        is_sci = a.get("is_science", False)
        cat   = "Science" if is_sci else "World News"
        bias  = a.get("bias_avg", 0.0)
        n     = a.get("n_sources", 1)
        agree_txt = f"{n} outlets agree" if n > 1 else "1 outlet"
        dot_pct = max(5, min(95, round((bias + 2) / 4 * 100)))
        badge_cls = "kd-badge-sci" if is_sci else "kd-badge-news"
        excerpt_raw = a.get("description") or ""
        excerpt = excerpt_raw[:137].rstrip() + "…" if len(excerpt_raw) > 137 else excerpt_raw
        bias_lbl = ("Far Left" if bias <= -1.2 else "Leans Left" if bias <= -0.4
                    else "Center-Left" if bias <= -0.15 else "Center" if bias <= 0.15
                    else "Center-Right" if bias <= 0.4 else "Leans Right" if bias <= 1.2
                    else "Far Right")
        cards.append(
            f'<div class="kd-sc" style="margin:10px 0">'
            f'<div class="kd-sc-top"><span class="kd-badge {badge_cls}">{cat}</span>'
            f'<span class="kd-agree {"kd-agree-med" if n>1 else "kd-agree-low"}">{agree_txt}</span></div>'
            f'<h3 style="margin:4px 0 6px"><a href="/{slug}">{title}</a></h3>'
            + (f'<p class="kd-card-excerpt">{excerpt}</p>' if excerpt else "")
            + f'<div class="kd-mini-bias"><span class="kd-mini-lbl">L</span>'
            f'<div class="kd-mini-track"><span class="kd-mini-dot" style="left:{dot_pct}%"></span></div>'
            f'<span class="kd-mini-lbl" style="text-align:right">R</span>'
            f'<span class="kd-bias-text">{bias_lbl}</span></div>'
            f'<div class="kd-sc-date">{__import__("datetime").datetime.strptime(date, "%Y-%m-%d").strftime("%b %d, %Y").replace(" 0", " ") if date else ""}</div>'
            f'</div>'
        )

    # Stats bar — today's summary
    from datetime import date as _date
    _today = str(_date.today())
    today_count = sum(1 for a in articles if a.get("date") == _today)
    sci_count = sum(1 for a in articles if a.get("is_science"))
    sci_pct = round(sci_count / len(articles) * 100) if articles else 0
    stats_bar = (
        f'<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;'
        f'padding:8px 14px;margin:0 0 14px;display:flex;gap:16px;flex-wrap:wrap;'
        f'font-size:12px;color:#1e40af;font-family:system-ui,sans-serif">'
        f'<span>&#128230; <strong>{today_count}</strong> stories today</span>'
        f'<span>&#128300; <strong>{sci_pct}%</strong> science</span>'
        f'<span>&#128202; <strong>{len(articles)}</strong> total articles</span>'
        f'<span style="margin-left:auto;color:#93c5fd">Updated 3× daily</span>'
        f'</div>'
    )

    hero = (
        '<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:14px 20px;margin:0 0 14px;font-family:system-ui,sans-serif">'
        '<p style="margin:0 0 8px;font-size:15px;color:#166534;font-weight:600;line-height:1.4">Science, world events, and discoveries — explained so kids can actually understand them.</p>'
        '<ul style="margin:0;padding-left:20px;font-size:13px;color:#166534;line-height:2">'
        '<li>Every story checked for age-appropriateness</li>'
        f'<li>{len(SOURCES)} sources, 70%+ science &amp; discovery</li>'
        '<li>Bias-rated so families can think for themselves</li>'
        '</ul>'
        '</div>'
    )
    trending_html = build_trending(manifest)
    new_block = (
        f'{HOMEPAGE_START}\n'
        + hero + stats_bar +
        f'<h2>Today\'s top kid news</h2>\n'
        + "\n".join(cards) +
        f'\n<p style="text-align:right;font-size:13px;margin-top:4px">'
        f'<a href="/news/today.html">Today</a> &middot; '
        f'<a href="/news/science.html">Science</a> &middot; '
        f'<a href="/news/technology.html">Technology</a> &middot; '
        f'<a href="/news/space.html">Space</a> &middot; '
        f'<a href="/news/animals.html">Animals</a> &middot; '
        f'<a href="/news/world.html">World</a> &middot; '
        f'<a href="/news/archive.html">Archive</a> &middot; '
        f'<a href="/digest/latest.html">Daily digest</a></p>\n'
        + trending_html +
        f'\n{HOMEPAGE_END}'
    )

    if HOMEPAGE_START in html:
        si = html.index(HOMEPAGE_START)
        ei = html.index(HOMEPAGE_END) + len(HOMEPAGE_END)
        html = html[:si] + new_block + html[ei:]
    else:
        # First run — replace the static "Today's top kid news" block
        old_h2    = "<h2>Today's top kid news</h2>"
        next_h2   = "<h2>For parents</h2>"
        if old_h2 in html and next_h2 in html:
            si = html.index(old_h2)
            ei = html.index(next_h2)
            html = html[:si] + new_block + "\n\n" + html[ei:]
        else:
            html = html.replace("</main>", new_block + "\n</main>")

    # Add RSS autodiscovery link if not already present
    rss_link = '<link rel="alternate" type="application/rss+xml" title="KiddieDaily RSS" href="/feed.xml">'
    if rss_link not in html and "</head>" in html:
        html = html.replace("</head>", f"  {rss_link}\n</head>")

    upload("index.html", html, "[scraper] Update homepage with latest 3 articles")


# ── RSS feed ──────────────────────────────────────────────────────────────────
def generate_rss_feed(manifest):
    articles = manifest.get("articles", [])
    BASE_URL = "https://kiddiedaily.com"
    now_rfc = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    items = []
    for a in sorted(articles, key=lambda x: x.get("date", ""), reverse=True)[:20]:
        slug  = a["slug"]
        title = a.get("display_title", a.get("title", "")).replace("&", "&amp;").replace("<", "&lt;")
        cat   = "Science" if a.get("is_science") else "World News"
        url   = f"{BASE_URL}/{slug}"
        try:
            d = datetime.strptime(a.get("date", ""), "%Y-%m-%d")
            pub = d.strftime("%a, %d %b %Y 10:00:00 +0000")
        except Exception:
            pub = now_rfc
        n     = a.get("n_sources", 1)
        agree = f"{n} outlet{'s' if n!=1 else ''} covering this story"
        raw_desc = a.get("description", "").strip()
        desc_text = (raw_desc[:200] + "…" if len(raw_desc) > 200 else raw_desc) if raw_desc else agree
        desc_safe = desc_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        _RSS_SUBCAT = {"space": "Space", "animals": "Animals", "history": "History",
                       "environment": "Environment", "technology": "Technology"}
        extra_cats = "".join(
            f"    <category>{_RSS_SUBCAT[c]}</category>\n"
            for c in (a.get("cats", []) or [])
            if c in _RSS_SUBCAT
        )
        items.append(
            f"  <item>\n"
            f"    <title>{title}</title>\n"
            f"    <link>{url}</link>\n"
            f"    <guid isPermaLink=\"true\">{url}</guid>\n"
            f"    <pubDate>{pub}</pubDate>\n"
            f"    <category>{cat}</category>\n"
            f"{extra_cats}"
            f"    <description>{desc_safe} — {agree}, bias-rated on KiddieDaily.</description>\n"
            f"  </item>"
        )

    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        '  <channel>\n'
        '    <title>KiddieDaily — News for Families</title>\n'
        f'    <link>{BASE_URL}</link>\n'
        f'    <atom:link href="{BASE_URL}/feed.xml" rel="self" type="application/rss+xml"/>\n'
        '    <description>Daily kid-friendly news with bias indicators and fact checks. Updated every morning.</description>\n'
        '    <language>en-us</language>\n'
        f'    <lastBuildDate>{now_rfc}</lastBuildDate>\n'
        '    <managingEditor>editors@kiddiedaily.com (KiddieDaily Editors)</managingEditor>\n'
        + "\n".join(items) + "\n"
        '  </channel>\n'
        '</rss>\n'
    )
    upload("feed.xml", feed, f"[scraper] RSS feed — {len(articles)} articles")
    print(f"  RSS: {len(articles)} items")

    # Category-specific feeds: /feed/science.xml, /feed/world.xml, /feed/space.xml, etc.
    _CAT_FEEDS = [
        ("science",     lambda a: a.get("is_science"),                      "Science",     "Kid-friendly science and nature news, bias-rated."),
        ("world",       lambda a: not a.get("is_science"),                   "World News",  "Kid-friendly world news, bias-rated."),
        ("space",       lambda a: "space"       in (a.get("cats") or []),    "Space",       "Space exploration and astronomy news for families."),
        ("animals",     lambda a: "animals"     in (a.get("cats") or []),    "Animals",     "Wildlife and animal science news for kids."),
        ("history",     lambda a: "history"     in (a.get("cats") or []),    "History",     "History and archaeology news for families."),
        ("environment", lambda a: "environment" in (a.get("cats") or []),    "Environment", "Climate and environment news for families."),
        ("technology",  lambda a: "technology"  in (a.get("cats") or []),    "Technology",  "Tech and innovation news for kids."),
    ]
    for cat_key, cat_filter, cat_label, cat_desc in _CAT_FEEDS:
        cat_articles = [a for a in sorted(articles, key=lambda x: x.get("date", ""), reverse=True) if cat_filter(a)][:20]
        if not cat_articles:
            continue
        cat_items = []
        for a in cat_articles:
            slug  = a["slug"]
            t     = a.get("display_title", a.get("title", "")).replace("&", "&amp;").replace("<", "&lt;")
            url   = f"{BASE_URL}/{slug}"
            try:
                d = datetime.strptime(a.get("date", ""), "%Y-%m-%d")
                pub = d.strftime("%a, %d %b %Y 10:00:00 +0000")
            except Exception:
                pub = now_rfc
            raw_d = a.get("description", "").strip()
            ds = (raw_d[:200] + "…" if len(raw_d) > 200 else raw_d).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            cat_items.append(
                f"  <item>\n    <title>{t}</title>\n    <link>{url}</link>\n"
                f"    <guid isPermaLink=\"true\">{url}</guid>\n    <pubDate>{pub}</pubDate>\n"
                f"    <category>{cat_label}</category>\n    <description>{ds}</description>\n  </item>"
            )
        cat_feed = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
            '  <channel>\n'
            f'    <title>KiddieDaily — {cat_label}</title>\n'
            f'    <link>{BASE_URL}/news/{cat_key}.html</link>\n'
            f'    <atom:link href="{BASE_URL}/feed/{cat_key}.xml" rel="self" type="application/rss+xml"/>\n'
            f'    <description>{cat_desc}</description>\n'
            '    <language>en-us</language>\n'
            f'    <lastBuildDate>{now_rfc}</lastBuildDate>\n'
            '    <managingEditor>editors@kiddiedaily.com (KiddieDaily Editors)</managingEditor>\n'
            + "\n".join(cat_items) + "\n"
            '  </channel>\n'
            '</rss>\n'
        )
        upload(f"feed/{cat_key}.xml", cat_feed, f"[scraper] RSS feed — {cat_label} ({len(cat_items)} articles)")
    print(f"  RSS: category feeds deployed (science, world, space, animals, history, environment, technology)")


# ── Parent Zone article list ───────────────────────────────────────────────────
PARENT_START = "<!-- PARENT_ARTICLES_START -->"
PARENT_END   = "<!-- PARENT_ARTICLES_END -->"

PARENT_CONTEXT = {
    "Science": "These stories cover recent discoveries in science, space, and nature. Great for sparking curiosity-driven conversations.",
    "World News": "These stories cover current events. Use them to introduce media literacy — discuss where each outlet stands politically.",
}

def update_parent_zone(manifest):
    """Keep parent-zone/index.html as a redirect to /parents/ (the canonical For-Parents page)."""
    redirect_html = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
        '<meta http-equiv="refresh" content="0;url=/parents/">'
        '<link rel="canonical" href="https://kiddiedaily.com/parents/">'
        '<title>Redirecting... — KiddieDaily</title></head><body>'
        '<p>Redirecting to <a href="/parents/">For Parents</a>…</p>'
        '</body></html>'
    )
    upload("parent-zone/index.html", redirect_html, "[scraper] parent-zone → /parents/ redirect")
    return

    articles = manifest.get("articles", [])
    if not articles:
        return

    r = gh("GET", f"/repos/{REPO}/contents/parent-zone/index.html")
    if r.get("_err"):
        print(f"    ⚠ Could not fetch parent-zone/index.html: {r}")
        return

    html = base64.b64decode(r["content"]).decode("utf-8")
    recent = sorted(articles, key=lambda x: x.get("date", ""), reverse=True)[:8]

    rows = []
    for a in recent:
        slug  = a["slug"]
        title = a.get("display_title", a.get("title", ""))[:90]
        date  = a.get("date", "")
        is_sci = a.get("is_science", False)
        cat   = "Science" if is_sci else "World News"
        n     = a.get("n_sources", 1)
        bias  = a.get("bias_avg", 0.0)
        bias_dir = "Left-leaning" if bias < -0.3 else ("Right-leaning" if bias > 0.3 else "Center")
        rows.append(
            f'<tr>'
            f'<td><a href="/{slug}">{title}</a></td>'
            f'<td>{cat}</td>'
            f'<td>{bias_dir} ({bias:+.1f})</td>'
            f'<td>{n}</td>'
            f'<td>{date}</td>'
            f'</tr>'
        )

    ctx_note = "These articles are curated daily by the KiddieDaily scraper — bias-rated and fact-check linked."
    new_block = (
        f'{PARENT_START}\n'
        f'<h2>Today\'s Articles — Parent View</h2>\n'
        f'<p style="font-size:14px;color:#4a5568;margin-bottom:12px">{ctx_note}</p>\n'
        f'<table style="width:100%;border-collapse:collapse;font-size:14px">\n'
        f'<thead><tr style="background:#1a4d80;color:#fff">'
        f'<th style="padding:8px;text-align:left">Story</th>'
        f'<th>Category</th><th>Bias</th><th>Sources</th><th>Date</th>'
        f'</tr></thead>\n'
        f'<tbody style="background:#fff">\n'
        + "\n".join(rows) +
        '\n</tbody></table>\n'
        f'<p style="font-size:12px;color:#718096;margin-top:8px">Bias scale: -2 far-left to +2 far-right. Sources = number of outlets covering the same story.</p>\n'
        f'{PARENT_END}'
    )

    if PARENT_START in html:
        si = html.index(PARENT_START)
        ei = html.index(PARENT_END) + len(PARENT_END)
        html = html[:si] + new_block + html[ei:]
    else:
        # Inject before </main> or before the "Coming soon" text
        for marker in ("</main>", "<p>Coming soon", "<h2>Coming soon"):
            if marker in html:
                html = html.replace(marker, new_block + "\n" + marker, 1)
                break

    upload("parent-zone/index.html", html, "[scraper] Update Parent Zone with latest articles table")


# ── Archive page ───────────────────────────────────────────────────────────────
def generate_archive(manifest):
    articles = manifest.get("articles", [])
    if not articles:
        return

    total = len(articles)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Lightweight shell — loads articles dynamically from /data/kd-articles.json
    # Reduces page size from ~670KB (embedded HTML) to ~15KB (dynamic render)
    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>News Archive — KiddieDaily</title>
<meta name="description" content="All KiddieDaily news articles — kid-friendly, bias-rated, fact-checked daily. {total} articles and counting.">
<meta property="og:title" content="KiddieDaily News Archive">
<meta property="og:description" content="{total} kid-safe, bias-rated articles. Searchable and filterable by category.">
<meta property="og:url" content="https://kiddiedaily.com/news/archive.html">
<link rel="canonical" href="https://kiddiedaily.com/news/archive.html">
<link rel="alternate" type="application/rss+xml" title="KiddieDaily RSS" href="/feed.xml">
{CSS}
<style>
.kd-sc{{background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:14px 18px 12px;margin:8px 0;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.kd-sc-top{{display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap}}
.kd-mini-bias{{display:flex;align-items:center;gap:6px;margin-top:8px}}
.kd-mini-lbl{{font-size:10px;font-weight:700;color:#718096;width:16px}}
.kd-mini-track{{flex:1;height:6px;border-radius:3px;background:linear-gradient(to right,#3182ce 0%,#805ad5 50%,#e53e3e 100%);position:relative}}
.kd-mini-dot{{position:absolute;top:-5px;width:16px;height:16px;background:#fff;border:2px solid #4a5568;border-radius:50%;transform:translateX(-50%)}}
.kd-sc h3 a{{color:#1a4d80;text-decoration:none}}
.kd-sc h3 a:hover{{text-decoration:underline}}
#arch-search{{width:100%;box-sizing:border-box;padding:10px 14px;font-size:16px;border:1px solid #cbd5e0;border-radius:8px;margin-bottom:4px;font-family:system-ui,sans-serif}}
#arch-search:focus{{border-color:#1a4d80;outline:3px solid rgba(26,77,128,.2)}}
#filter-btns{{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}}
#filter-btns button{{background:#f7fafc;border:1px solid #e2e8f0;border-radius:20px;padding:5px 14px;cursor:pointer;font-size:13px;font-family:system-ui,sans-serif;min-height:36px}}
#filter-btns button.active{{background:#1a4d80;color:#fff;border-color:#1a4d80}}
#arch-count{{font-size:14px;color:#718096;font-family:system-ui,sans-serif;margin:0 0 16px;min-height:20px}}
.arch-date-hdr{{font-size:.85em;color:#718096;font-weight:600;letter-spacing:1px;text-transform:uppercase;margin:24px 0 8px}}
</style>
</head><body>
{HEADER}
<main id="main">
<h1 style="font-size:28px;margin-bottom:4px">News Archive</h1>
<p style="color:#718096;font-family:system-ui,sans-serif;font-size:14px;margin:0 0 16px">{total} articles &middot; Updated {today_str}</p>

<input type="search" id="arch-search" placeholder="Search {total} articles..." aria-label="Search archive">
<p id="arch-count"></p>
<div id="filter-btns">
  <button class="active" onclick="setFilter('all',this)">All</button>
  <button onclick="setFilter('science',this)">&#128300; Science</button>
  <button onclick="setFilter('world',this)">&#127758; World</button>
  <button onclick="setFilter('space',this)">&#128640; Space</button>
  <button onclick="setFilter('animals',this)">&#128062; Animals</button>
  <button onclick="setFilter('history',this)">&#127963; History</button>
  <button onclick="setFilter('environment',this)">&#127807; Env</button>
  <button onclick="setFilter('technology',this)">&#128187; Tech</button>
</div>

<div id="archive-list"><p style="color:#718096;font-family:system-ui,sans-serif">Loading articles…</p></div>

<div style="text-align:center;margin-top:24px">
  <button id="load-more" onclick="loadMore()" style="display:none;background:#1a4d80;color:#fff;border:none;padding:10px 28px;border-radius:6px;font-size:14px;cursor:pointer;font-family:system-ui,sans-serif">Load more articles</button>
</div>

<p style="text-align:center;margin-top:32px;font-size:13px;color:#718096;font-family:system-ui,sans-serif">
  <a href="/feed.xml" style="color:#1a4d80">Subscribe via RSS</a> &middot;
  <a href="/news/today.html" style="color:#1a4d80">Today&#39;s news</a> &middot;
  <a href="/news/" style="color:#1a4d80">Latest news</a> &middot;
  <a href="#top" style="color:#1a4d80">Back to top &uarr;</a>
</p>
</main>
{FOOTER}

<script>
(function() {{
  var allArticles = [], filtered = [], activeFilter = 'all', query = '', offset = 0;
  var PAGE = 40;

  var listEl  = document.getElementById('archive-list');
  var countEl = document.getElementById('arch-count');
  var moreBtn = document.getElementById('load-more');
  var searchEl = document.getElementById('arch-search');

  var MO=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  var TODAY_STR=new Date().toISOString().slice(0,10);
  function fmtDate(d){{var p=d?d.split('-'):[];return p.length===3?MO[parseInt(p[1])-1]+' '+parseInt(p[2])+', '+p[0]:d||'';}}
  function biasLabel(b) {{
    return b <= -1.2 ? 'Far Left' : b <= -0.4 ? 'Leans Left' : b <= -0.15 ? 'Center-Left'
         : b <= 0.15 ? 'Center' : b <= 0.4 ? 'Center-Right' : b <= 1.2 ? 'Leans Right' : 'Far Right';
  }}

  function renderCard(a) {{
    var isSci = a.is_science || a.category === 'science';
    var badge = isSci ? '<span class="kd-badge kd-badge-sci">Science</span>' : '<span class="kd-badge kd-badge-news">World News</span>';
    var n = a.n_sources || 1;
    var bias = a.bias_avg || 0;
    var dot = Math.max(5, Math.min(95, Math.round((bias + 2) / 4 * 100)));
    var bLbl = biasLabel(bias);
    var src = n === 1 ? '1 outlet' : n + ' outlets';
    var newBadge = a.date === TODAY_STR ? '<span style="font-size:10px;background:#dc2626;color:#fff;padding:1px 6px;border-radius:20px;font-weight:700;margin-left:5px">NEW</span>' : '';
    return '<div class="kd-sc">'
      + '<div class="kd-sc-top">' + badge + newBadge + '<span style="font-size:11px;color:#718096;margin-left:auto">' + src + '</span></div>'
      + '<h3 style="margin:4px 0 6px"><a href="/' + a.slug + '">' + a.title + '</a></h3>'
      + '<div class="kd-mini-bias"><span class="kd-mini-lbl">L</span>'
      + '<div class="kd-mini-track"><span class="kd-mini-dot" style="left:' + dot + '%"></span></div>'
      + '<span class="kd-mini-lbl" style="text-align:right">R</span>'
      + '<span style="font-size:10px;color:#718096;margin-left:6px">' + bLbl + '</span></div>'
      + '<div style="font-size:11px;color:#718096;margin-top:4px">' + fmtDate(a.date) + '</div>'
      + '</div>';
  }}

  function matchFilter(a, f) {{
    if (f === 'all') return true;
    if (f === 'science') return a.is_science;
    if (f === 'world') return !a.is_science;
    return (a.cats || []).indexOf(f) !== -1;
  }}

  function applyFilter() {{
    var q = query.toLowerCase();
    filtered = allArticles.filter(function(a) {{
      var catOk = matchFilter(a, activeFilter);
      var qOk = !q || (a.title && a.title.toLowerCase().indexOf(q) !== -1)
               || (a.description && a.description.toLowerCase().indexOf(q) !== -1);
      return catOk && qOk;
    }});
    offset = 0;
    renderPage();
  }}

  function renderPage() {{
    var chunk = filtered.slice(0, offset + PAGE);
    // Group by date
    var byDate = {{}};
    chunk.forEach(function(a) {{ (byDate[a.date || 'Unknown'] = byDate[a.date || 'Unknown'] || []).push(a); }});
    var html = '';
    Object.keys(byDate).sort().reverse().forEach(function(d) {{
      html += '<h2 class="arch-date-hdr">' + fmtDate(d) + '</h2>';
      byDate[d].forEach(function(a) {{ html += renderCard(a); }});
    }});
    listEl.innerHTML = html || '<p style="color:#718096;font-family:system-ui,sans-serif">No articles matched.</p>';
    offset = Math.min(offset + PAGE, filtered.length);
    countEl.textContent = filtered.length + ' article' + (filtered.length === 1 ? '' : 's')
      + (query ? " for '" + query + "'" : '') + (activeFilter !== 'all' ? ' in ' + activeFilter : '');
    moreBtn.style.display = offset < filtered.length ? '' : 'none';
  }}

  function loadMore() {{ renderPage(); }}
  window.loadMore = loadMore;

  function setFilter(cat, btn) {{
    activeFilter = cat;
    document.querySelectorAll('#filter-btns button').forEach(function(b) {{ b.classList.remove('active'); }});
    btn.classList.add('active');
    applyFilter();
  }}
  window.setFilter = setFilter;

  searchEl.addEventListener('input', function() {{
    query = this.value.trim();
    applyFilter();
  }});

  fetch('/data/kd-articles.json')
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
      allArticles = data.sort(function(a, b) {{ return b.date < a.date ? -1 : 1; }});
      searchEl.placeholder = 'Search ' + allArticles.length + ' articles…';
      applyFilter();
    }})
    .catch(function() {{
      listEl.innerHTML = '<p style="color:#718096;font-family:system-ui,sans-serif">Could not load articles. <a href="/search.html">Try search</a>.</p>';
    }});
}})();
</script>
</body></html>"""

    upload("news/archive.html", page, f"[scraper] Archive page (dynamic) — {total} articles")
    print(f"  Archive: {total} articles")


# ── Category keyword sets (shared by JSON index and page generator) ───────────
_CAT_SPACE_KW = {
    "space", "nasa", "galaxy", "planet", "star", "asteroid", "mars", "moon", "rocket", "telescope",
    "solar storm", "solar flare", "solar wind", "solar eruption", "coronal mass ejection", "geomagnetic",
    "sun ", " sun", "orbit", "comet", "black hole", "nebula", "eclipse", "exoplanet", "spacecraft",
    "cosmos", "aurora borealis", "aurora australis", "northern lights", "southern lights",
    "space weather", "ionosphere", "magnetosphere", "heliosphere",
    "venus", "jupiter", "saturn", "mercury", "neptune", "uranus", "pluto",
    "milky way", "supernova", "pulsar", "quasar", "big bang", "dark matter", "dark energy",
    "hubble", "james webb", "jwst", "voyager", "cassini", "juno probe", "perseverance",
    "space station", "iss ", "astronaut", "cosmonaut", "spacewalk", "launch vehicle",
}
_CAT_ANIMAL_KW = {"animal", "animals", "species", "whale", "shark", "bird", "birds", "dog", "dogs", "cat", "cats", "wildlife", "octopus", "insect", "insects", "turtle", "turtles", "fish", "elephant", "elephants", "bear", "bears", "wolf", "wolves", "lion", "lions", "tiger", "tigers", "dolphin", "dolphins", "penguin", "penguins", "seal", "seals", "zoo", "habitat", "extinct", "endangered", "mammal", "reptile", "amphibian", "coral", "reef", "migration", "nest", "prey", "predator", "marine", "ocean life", "bee", "bees", "butterfly", "butterflies"}
_CAT_ENV_KW = {"climate", "environment", "pollution", "forest", "ocean", "glacier", "wildfire", "drought", "flood", "hurricane", "tornado", "volcano", "earthquake", "recycling", "carbon", "solar", "renewable", "ecosystem", "biodiversity", "rainforest", "deforestation",
               "sea level", "permafrost", "arctic", "antarctic", "polar ice",
               "emissions", "greenhouse gas", "methane", "carbon dioxide",
               "microplastic", "contamination", "pesticide", "toxic waste",
               "conservation", "nature reserve", "reforestation", "rewilding",
               "wetland", "mangrove", "peat", "estuary",
               "heat wave", "extreme heat", "sea ice", "ice sheet", "ice cap",
               "clean energy", "wind farm", "hydropower",
               "water scarcity", "water quality", "groundwater", "coral bleach"}
_CAT_HISTORY_KW = {
    "ancient", "prehistoric", "medieval", "bronze age", "iron age", "stone age", "neolithic",
    "paleolithic", "19th century", "18th century", "17th century", "16th century",
    "world war", "war ii", "civil war", "cold war",
    "renaissance", "byzantine", "ottoman", "ming dynasty", "qing dynasty",
    "mesopotamia", "sumerian", "babylonian", "assyrian", "persian empire",
    "viking", "roman", "greek", "pharaoh", "mayan", "aztec", "inca", "mongol",
    "neanderthal", "homo naledi", "homo sapiens", "hominid", "hominin",
    "native american", "indigenous", "colonial",
    "samurai", "shogun", "ptolemaic", "norse", "celtic", "druid",
    "greek mythology", "roman mythology", "norse mythology",
    "fossil", "dinosaur", "archaeolog", "artifact", "excavat",
    "ruin", "pyramid", "empire", "revolution", "civilization",
    "million year", "thousand year", "history of", "history behind",
    "historical", "archives", "uncovered a", "were discovered",
    "ancient tomb", "burial site", "royal tomb", "human remains", "ancient remains",
    "stone tools", "cave painting", "pictograph", "hieroglyph", "cuneiform",
    "ancient writing", "ancient text", "ancient dna", "radiocarbon",
    "ancient city", "lost city", "field expedition", "dig site",
    "mummy", "mummified", "sarcophagus", "bog body",
    "paleoanthropolog", "paleoarchaeolog", "ancient genome", "ancient migration",
    "ancient skull", "ancient skeleton", "ancient bone", "ancient teeth",
    "silk road", "trade route", "ancient trade", "ancient map",
    "ancient ship", "shipwreck", "ancient kingdom", "ancient empire",
    "world history", "cultural history", "oral history",
    "early human", "early homo", "first humans",
    "maginot", "casablanca conference", "intermediate period",
    "kingdom of egypt", "old kingdom", "middle kingdom", "new kingdom",
    "treaty of", "siege of", "dynasty of",
    "pantheon", "mythology", "ancient god", "ancient goddess",
    "ancient religion", "ancient myth", "ancient legend",
    "ancient soldier", "ancient warrior", "ancient weapon",
    "fortress", "ancient fortress", "ancient wall", "ancient palace",
    "pharaoh of", "king of egypt", "queen of egypt",
    "roman emperor", "roman senate", "roman republic",
    "greek empire", "greek city", "greek philosophy",
}
_CAT_TECH_KW = {
    "quantum", "robot", "robotics", "ai ", "artificial intelligence", "machine learning",
    "nanosensor", "nanotechnology", "semiconductor", "computer chip", "microchip",
    "algorithm", "software", "engineering", "invention", "cryogenic",
    "3d print", "drone", "satellite commun", "electric vehicle", "battery",
    "alloy", "polymer", "material science", "materials science",
    "nuclear reactor", "nuclear fusion", "photovoltaic", "wind turbine",
    "internet", "cybersecurity", "encryption", "data center", "cloud computing",
    "fiber optic", "processor", "transistor", "laser tech",
    "gene editing", "crispr", "synthetic biology", "bioengineering",
    "autonomous vehicle", "self-driving", "exoskeleton", "prosthetic",
    "wearable", "particle accelerator", "superconductor",
    "deep learning", "neural network", "computer vision",
    "bionic", "microbot", "quantum computing", "quantum sensor",
    "solar cell", "solar panel", "energy storage", "supercapacitor",
    "spectroscop", "electron microscope", "carbon nanotube",
    "spacecraft design", "rocket engine", "space telescope",
    "imaging technique", "remote sensing", "carbon fiber",
    "molecular machine", "microfluidic", "lab-on-a-chip",
    "neutrino detector", "gravitational wave detector",
    "haptic", "augmented reality", "virtual reality",
}
_CAT_SOURCES = {
    "space":       {"NASA", "EarthSky", "Space.com"},
    "animals":     {"Mongabay", "BBC Newsround"},
    "history":     {"JSTOR Daily", "World History Encyclopedia", "Archaeology", "Medievalists", "HistoryHit", "Atlas Obscura", "Smithsonian"},
    "environment": {"NASA Earth", "Carbon Brief", "Hakai Magazine", "Inside Climate News"},
    "technology":  {"MIT Tech Review", "IEEE Spectrum", "MIT News", "Ars Technica Science"},
}
_CAT_KEYWORDS = {
    "space": _CAT_SPACE_KW, "animals": _CAT_ANIMAL_KW, "environment": _CAT_ENV_KW,
    "history": _CAT_HISTORY_KW, "technology": _CAT_TECH_KW,
}

def _article_cats(a):
    haystack = (a.get("title","") + " " + a.get("slug","")).lower()
    src = a.get("source_name","")
    cats = ["science" if a.get("is_science") else "world"]
    for cname, kws in _CAT_KEYWORDS.items():
        if src in _CAT_SOURCES.get(cname, set()) or any(k in haystack for k in kws):
            cats.append(cname)
    return cats


# ── Category pages (dynamic JS shell — loads from kd-articles.json) ───────────
def generate_category_pages(manifest):
    articles = manifest.get("articles", [])
    total = len(articles)

    _CAT_META = {
        "science":     ("🔬", "Science",     "Space, animals, inventions, and discoveries — science stories for curious kids.", "#34d399"),
        "world":       ("🌍", "World News",  "What's happening around the world, explained for families.",                     "#60a5fa"),
        "space":       ("🚀", "Space",       "Rockets, planets, galaxies, and NASA discoveries — space news for kids.",        "#a78bfa"),
        "animals":     ("🐾", "Animals",     "Wildlife, sea creatures, and amazing animals from around the world.",            "#fbbf24"),
        "history":     ("🏛", "History",     "Fossils, ancient civilizations, and discoveries that unlock the past.",          "#f9a8d4"),
        "environment": ("🌿", "Environment", "Climate, oceans, forests, and Earth's ecosystems — environment news for kids.", "#6ee7b7"),
        "technology":  ("💻", "Technology",  "AI, robots, engineering, and inventions — tech news explained for families.",   "#93c5fd"),
    }
    _PILL_COLORS = {
        "science": ("#d1fae5","#065f46"), "technology": ("#e0e7ff","#3730a3"),
        "space": ("#ede9fe","#5b21b6"), "animals": ("#fef3c7","#92400e"),
        "world": ("#dbeafe","#1e40af"), "environment": ("#dcfce7","#166534"),
        "history": ("#fce7f3","#9d174d"),
    }

    for key, (icon, label, description, accent) in _CAT_META.items():
        # count articles for this category (for meta description)
        n_cat = sum(1 for a in articles if key in _article_cats(a))

        # Build cross-category pill nav
        pills = []
        for ck, (ci, cl, _, _2) in _CAT_META.items():
            bg, fg = _PILL_COLORS.get(ck, ("#f3f4f6","#374151"))
            outline = f";outline:2px solid {fg};outline-offset:1px" if ck == key else ""
            pills.append(
                f'<a href="/news/{ck}.html" style="background:{bg};color:{fg};padding:4px 12px;'
                f'border-radius:20px;font-size:12px;font-weight:700;text-decoration:none{outline}">'
                f'{ci} {cl}</a>'
            )
        cross_nav = '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:20px">' + ''.join(pills) + '</div>'

        page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{icon} {label} News for Kids — KiddieDaily</title>
<meta name="description" content="{description} {n_cat} stories.">
<meta property="og:title" content="KiddieDaily {label} News">
<meta property="og:description" content="{description}">
<meta property="og:image" content="https://kiddiedaily.com/og-science.svg">
<meta property="og:url" content="https://kiddiedaily.com/news/{key}.html">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="https://kiddiedaily.com/news/{key}.html">
<link rel="alternate" type="application/rss+xml" title="KiddieDaily {label} RSS" href="/feed/{key}.xml">
<link rel="alternate" type="application/rss+xml" title="KiddieDaily All News" href="/feed.xml">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"Home","item":"https://kiddiedaily.com"}},{{"@type":"ListItem","position":2,"name":"News","item":"https://kiddiedaily.com/news/"}},{{"@type":"ListItem","position":3,"name":"{label}","item":"https://kiddiedaily.com/news/{key}.html"}}]}}</script>
{CSS}
<style>
.kd-sc{{background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:14px 18px 12px;margin:10px 0;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.kd-sc-top{{display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap}}
.kd-mini-bias{{display:flex;align-items:center;gap:6px;margin-top:8px}}
.kd-mini-lbl{{font-size:10px;font-weight:700;color:#718096;width:16px}}
.kd-mini-track{{flex:1;height:6px;border-radius:3px;background:linear-gradient(to right,#3182ce 0%,#805ad5 50%,#e53e3e 100%);position:relative}}
.kd-mini-dot{{position:absolute;top:-5px;width:16px;height:16px;background:#fff;border:2px solid #4a5568;border-radius:50%;transform:translateX(-50%)}}
.kd-sc h3 a{{color:#1a4d80;text-decoration:none}}
.kd-sc h3 a:hover{{text-decoration:underline}}
#cat-search{{width:100%;box-sizing:border-box;padding:10px 14px;font-size:16px;border:1px solid #cbd5e0;border-radius:8px;margin-bottom:16px;font-family:system-ui,sans-serif}}
.cat-more-btn{{display:block;width:100%;background:none;border:1px solid #cbd5e0;padding:10px;border-radius:6px;cursor:pointer;font-family:system-ui,sans-serif;color:#1a4d80;font-size:13px;margin:10px 0 4px;text-align:center}}
</style>
</head><body>
{HEADER}
<main id="main">
<div style="display:flex;align-items:baseline;gap:12px;margin-bottom:4px">
<h1 style="font-size:28px;margin:0">{icon} {label} News</h1>
<span id="cat-count" style="font-size:13px;color:#718096;font-family:system-ui,sans-serif">{n_cat} stories</span>
</div>
<p style="color:#718096;font-family:system-ui,sans-serif;font-size:14px;margin:0 0 14px">{description}</p>
{cross_nav}
<input type="search" id="cat-search" placeholder="Search {label} stories..." aria-label="Search {label} articles">
<div id="cat-multi" style="display:none;background:#fff8e1;border:1px solid #fde68a;border-radius:8px;padding:8px 14px;margin-bottom:16px;font-size:13px;font-family:system-ui,sans-serif;color:#92400e"></div>
<div id="cat-list"></div>
<button id="cat-more" class="cat-more-btn" style="display:none" onclick="catLoadMore()"></button>
<div id="cat-empty" style="display:none;color:#718096;font-family:system-ui,sans-serif;padding:20px 0">No articles found in this category yet.</div>
<p style="text-align:center;margin-top:32px;font-size:13px;color:#718096;font-family:system-ui,sans-serif">
  <a href="/news/archive.html" style="color:#1a4d80">Full archive ({total} total)</a> &middot;
  <a href="/news/today.html" style="color:#1a4d80">Today&#39;s news</a> &middot;
  <a href="/feed/{key}.xml" style="color:#1a4d80">{label} RSS feed</a> &middot;
  <a href="/feed.xml" style="color:#718096">All news RSS</a>
</p>
</main>
{FOOTER}
<script>
(function(){{
var CAT='{key}',PAGE=20,arts=[],off=0,q='';
var BL=[[-1.2,'Far Left'],[-0.4,'Leans Left'],[-0.15,'Center-Left'],[0.15,'Center'],[0.4,'Center-Right'],[1.2,'Leans Right'],[99,'Far Right']];
function blbl(b){{for(var i=0;i<BL.length;i++)if(b<=BL[i][0])return BL[i][1];return'Far Right';}}
var BC='{("kd-badge-sci" if key != "world" else "kd-badge-news")}';
var MO=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];var TODAY_STR=new Date().toISOString().slice(0,10);
function fmtDate(d){{var p=d?d.split('-'):[];return p.length===3?MO[parseInt(p[1])-1]+' '+parseInt(p[2])+', '+p[0]:d||'';}}
function card(a){{
  var b=a.bias_avg||0,dp=Math.max(5,Math.min(95,Math.round((b+2)/4*100)));
  var ttl=a.title||'';var dt=a.date||'';var n=a.n_sources||1;
  var multi=n>1?'<span style="font-size:10px;background:#fff8e1;color:#92400e;border:1px solid #fde68a;padding:1px 7px;border-radius:20px;font-weight:700;margin-left:6px">'+n+' outlets</span>':'';
  var newBadge=dt===TODAY_STR?'<span style="font-size:10px;background:#dc2626;color:#fff;padding:1px 6px;border-radius:20px;font-weight:700;margin-left:5px">NEW</span>':'';
  var ex=a.description?a.description.slice(0,137)+(a.description.length>137?'…':''):'';
  return '<div class="kd-sc" data-title="'+ttl.toLowerCase()+'">'
    +'<div class="kd-sc-top"><span class="kd-badge '+BC+'">{icon} {label}</span>'+multi+newBadge
    +'<span style="font-size:11px;color:#718096;margin-left:auto">'+n+' outlet'+(n!==1?'s':'')+'&middot;'+fmtDate(dt)+'</span></div>'
    +'<h3 style="margin:4px 0 6px"><a href="/'+a.slug+'">'+ttl+'</a></h3>'
    +(ex?'<p class="kd-card-excerpt">'+ex+'</p>':'')
    +'<div class="kd-mini-bias"><span class="kd-mini-lbl">L</span>'
    +'<div class="kd-mini-track"><span class="kd-mini-dot" style="left:'+dp+'%"></span></div>'
    +'<span class="kd-mini-lbl" style="text-align:right">R</span>'
    +'<span class="kd-bias-text">'+blbl(b)+'</span></div></div>';
}}
function renderSlice(){{
  var list=document.getElementById('cat-list');
  var visible=q?arts.filter(function(a){{return((a.title||'')+' '+(a.description||'')).toLowerCase().includes(q);}})
               :arts;
  var slice=visible.slice(off,off+PAGE);
  slice.forEach(function(a){{var d=document.createElement('div');d.innerHTML=card(a);list.appendChild(d.firstChild);}});
  off+=slice.length;
  var rem=visible.length-off;
  var btn=document.getElementById('cat-more');
  if(rem>0){{btn.style.display='block';btn.textContent='Load '+Math.min(rem,PAGE)+' more';}}
  else btn.style.display='none';
}}
window.catLoadMore=function(){{renderSlice();}};
fetch('/data/kd-articles.json').then(function(r){{return r.json();}}).then(function(data){{
  arts=data.filter(function(a){{return Array.isArray(a.cats)&&a.cats.indexOf(CAT)>=0;}});
  document.getElementById('cat-count').textContent=arts.length+' stories';
  var multi=arts.filter(function(a){{return(a.n_sources||1)>1;}});
  if(multi.length){{
    var el=document.getElementById('cat-multi');
    el.style.display='';
    el.innerHTML='&#x1F4F0; <strong>'+multi.length+'</strong> stories covered by multiple news outlets — look for the yellow badge';
  }}
  if(!arts.length){{document.getElementById('cat-empty').style.display='';return;}}
  renderSlice();
}}).catch(function(){{document.getElementById('cat-empty').style.display='';}});
document.getElementById('cat-search').addEventListener('input',function(){{
  q=this.value.toLowerCase().trim();
  off=0;
  document.getElementById('cat-list').innerHTML='';
  renderSlice();
}});
}})();
</script>
</body></html>"""

        upload(f"news/{key}.html", page, f"[scraper] {label} category page — dynamic JS, {n_cat} articles")
    print(f"  Category pages: dynamic JS shells for {len(_CAT_META)} categories ({total} total articles)")


# ── Today's news page ─────────────────────────────────────────────────────────
def generate_today_page(manifest, today):
    articles = manifest.get("articles", [])
    todays    = [a for a in articles if a.get("date") == today]
    sci_today   = [a for a in todays if a.get("is_science")]
    world_today = [a for a in todays if not a.get("is_science")]
    total_today = len(todays)

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Today&#39;s Kid News — {today} | KiddieDaily</title>
<meta name="description" content="Today&#39;s kid-safe, bias-rated news for families. {total_today} articles — {len(sci_today)} science, {len(world_today)} world news. Updated {today}.">
<meta property="og:title" content="KiddieDaily — Today&#39;s News ({today})">
<meta property="og:description" content="{total_today} articles today: {len(sci_today)} science, {len(world_today)} world news. Bias-rated, kid-safe.">
<meta property="og:image" content="https://kiddiedaily.com/og-science.svg">
<meta property="og:url" content="https://kiddiedaily.com/news/today.html">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="https://kiddiedaily.com/news/today.html">
<link rel="alternate" type="application/rss+xml" title="KiddieDaily RSS" href="/feed.xml">
{CSS}
<style>
#today-search{{width:100%;box-sizing:border-box;padding:10px 14px;font-size:16px;border:1px solid #cbd5e0;border-radius:8px;margin-bottom:16px;font-family:system-ui,sans-serif}}
.td-card{{padding:14px 0;border-bottom:1px solid #e5e7eb}}
.td-card a{{font-size:15px;font-weight:600;color:#1a4d80;text-decoration:none;line-height:1.35;display:block;margin-bottom:4px}}
.td-card .td-ex{{margin:0 0 6px;font-size:13px;color:#4a5568;line-height:1.4;font-family:system-ui,sans-serif}}
.td-more-btn{{display:block;width:100%;background:none;border:1px solid #cbd5e0;padding:10px;border-radius:6px;cursor:pointer;font-family:system-ui,sans-serif;color:#1a4d80;font-size:13px;margin:8px 0 4px;text-align:center}}
</style>
</head><body>
{HEADER}
<main id="main" style="max-width:780px;margin:0 auto;padding:32px 24px 64px">
<h1 style="font-size:28px;margin:0 0 4px">Today&#39;s News</h1>
<p style="font-size:14px;color:#718096;font-family:system-ui,sans-serif;margin:0 0 16px">
{today} &middot; <span id="td-count">{total_today}</span> articles &middot;
<a href="/parents/" style="color:#1a4d80">For Parents</a> &middot;
<a href="/digest/latest.html" style="color:#1a4d80">Daily Digest</a> &middot;
<a href="/feed.xml" style="color:#1a4d80">RSS</a>
</p>
<input type="search" id="today-search" placeholder="Search today&#39;s stories..." aria-label="Search today's news">
<div id="td-jump" style="display:none;background:#f7fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 16px;margin:0 0 10px;display:flex;gap:12px;flex-wrap:wrap;font-family:system-ui,sans-serif;font-size:13px;align-items:center">
  <span style="color:#718096;font-weight:600">Jump to:</span>
  <a href="#td-sci" style="color:#065f46;background:#d1fae5;padding:4px 12px;border-radius:20px;text-decoration:none;font-weight:600">&#x1f52c; Science (<span id="td-sci-n">0</span>)</a>
  <a href="#td-world" style="color:#1e40af;background:#dbeafe;padding:4px 12px;border-radius:20px;text-decoration:none;font-weight:600">&#x1f30d; World News (<span id="td-world-n">0</span>)</a>
</div>
<div id="td-subcats" style="display:none;background:#f7fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 16px;margin:0 0 20px;flex-wrap:wrap;gap:10px;font-family:system-ui,sans-serif;font-size:13px;align-items:center">
  <span style="color:#718096;font-weight:600">Browse by topic:</span>
  <a href="/news/space.html" style="color:#5b21b6;background:#ede9fe;padding:4px 12px;border-radius:20px;text-decoration:none;font-weight:600">&#x1f680; Space (<span id="td-spc-n">0</span>)</a>
  <a href="/news/animals.html" style="color:#92400e;background:#fef3c7;padding:4px 12px;border-radius:20px;text-decoration:none;font-weight:600">&#x1f43e; Animals (<span id="td-ani-n">0</span>)</a>
  <a href="/news/history.html" style="color:#9d174d;background:#fce7f3;padding:4px 12px;border-radius:20px;text-decoration:none;font-weight:600">&#x1f3db; History (<span id="td-his-n">0</span>)</a>
  <a href="/news/environment.html" style="color:#166534;background:#dcfce7;padding:4px 12px;border-radius:20px;text-decoration:none;font-weight:600">&#x1f33f; Env (<span id="td-env-n">0</span>)</a>
  <a href="/news/technology.html" style="color:#3730a3;background:#e0e7ff;padding:4px 12px;border-radius:20px;text-decoration:none;font-weight:600">&#x1f4bb; Tech (<span id="td-tec-n">0</span>)</a>
</div>
<div id="td-empty" style="display:none;color:#718096;font-family:system-ui,sans-serif;padding:20px 0">No articles yet today — check back after 6am ET.</div>
<div id="td-sci-sec">
  <div style="display:flex;align-items:center;gap:10px;margin:28px 0 4px;padding-bottom:8px;border-bottom:2px solid #34d399">
    <span style="font-size:20px">&#x1f52c;</span>
    <h2 id="td-sci" style="margin:0;font-size:18px;color:#1a4d80">Science &amp; Discovery</h2>
    <span id="td-sci-hdr" style="font-size:12px;color:#718096;font-family:system-ui,sans-serif;margin-left:auto"></span>
  </div>
  <div id="td-sci-list"></div>
  <button id="td-sci-more" class="td-more-btn" style="display:none" onclick="tdLoad('sci')"></button>
  <div style="text-align:center;padding:14px 0;border-top:1px solid #e5e7eb;margin-top:4px">
    <a href="/news/science.html" style="font-size:13px;color:#1a4d80;font-family:system-ui,sans-serif;font-weight:600">&#x1f52c; See all science articles &rarr;</a>
  </div>
</div>
<div id="td-world-sec">
  <div style="display:flex;align-items:center;gap:10px;margin:28px 0 4px;padding-bottom:8px;border-bottom:2px solid #60a5fa">
    <span style="font-size:20px">&#x1f30d;</span>
    <h2 id="td-world" style="margin:0;font-size:18px;color:#1a4d80">World News</h2>
    <span id="td-world-hdr" style="font-size:12px;color:#718096;font-family:system-ui,sans-serif;margin-left:auto"></span>
  </div>
  <div id="td-world-list"></div>
  <button id="td-world-more" class="td-more-btn" style="display:none" onclick="tdLoad('world')"></button>
  <div style="text-align:center;padding:14px 0;border-top:1px solid #e5e7eb;margin-top:4px">
    <a href="/news/world.html" style="font-size:13px;color:#1a4d80;font-family:system-ui,sans-serif;font-weight:600">&#x1f30d; See all world news &rarr;</a>
  </div>
</div>
<p style="text-align:center;margin-top:32px;font-size:13px;color:#718096;font-family:system-ui,sans-serif">
<a href="/news/archive.html" style="color:#1a4d80">Full archive</a> &middot;
<a href="/news/science.html" style="color:#1a4d80">Science</a> &middot;
<a href="/news/world.html" style="color:#1a4d80">World News</a> &middot;
<a href="#top" style="color:#1a4d80">Back to top &uarr;</a>
</p>
</main>
{FOOTER}
<script>
(function(){{
var TODAY='{today}',SCI_PG=15,WLD_PG=10,sci=[],world=[],sciOff=0,wldOff=0;
var BL=[[-1.2,'Far Left'],[-0.4,'Leans Left'],[-0.15,'Center-Left'],[0.15,'Center'],[0.4,'Center-Right'],[1.2,'Leans Right'],[99,'Far Right']];
function blbl(b){{for(var i=0;i<BL.length;i++)if(b<=BL[i][0])return BL[i][1];return'Far Right';}}
function card(a){{
  var b=a.bias_avg||0,dp=Math.max(5,Math.min(95,Math.round((b+2)/4*100)));
  var isSci=!!a.is_science;
  var bc=isSci?'kd-badge-sci':'kd-badge-news';
  var cat=isSci?'Science':'World News';
  var multi=a.n_sources>1?'<span style="font-size:10px;background:#fff8e1;color:#92400e;border:1px solid #fde68a;padding:1px 7px;border-radius:20px;font-weight:700;margin-left:6px">'+a.n_sources+' outlets</span>':'';
  var ttl=a.display_title||a.title||'';
  var ex=a.description?a.description.slice(0,120)+(a.description.length>120?'…':''):'';
  var CCLR={{'space':'#ede9fe;color:#5b21b6','animals':'#fef3c7;color:#92400e','history':'#fce7f3;color:#9d174d','environment':'#dcfce7;color:#166534','technology':'#e0e7ff;color:#3730a3'}};
  var subcats=(a.cats||[]).filter(function(c){{return c!=='science'&&c!=='world';}});
  var ctags=subcats.slice(0,2).map(function(c){{var s=CCLR[c]||'#f3f4f6;color:#374151';return'<span style="font-size:10px;background:'+s+';padding:1px 7px;border-radius:20px;font-weight:600;margin-left:5px">'+c+'</span>';}}).join('');
  return '<div class="td-card" data-title="'+ttl.toLowerCase()+'">'
    +'<div style="margin-bottom:5px"><span class="kd-badge '+bc+'" style="font-size:10px">'+cat+'</span>'+ctags+multi+'</div>'
    +'<a href="/'+a.slug+'">'+ttl+'</a>'
    +(ex?'<p class="td-ex">'+ex+'</p>':'')
    +'<div style="display:flex;align-items:center;gap:6px">'
    +'<span style="font-size:10px;color:#a0aec0">L</span>'
    +'<div style="width:80px;height:5px;border-radius:3px;background:linear-gradient(to right,#3182ce,#805ad5,#e53e3e);position:relative;flex-shrink:0">'
    +'<span style="position:absolute;top:-4px;left:'+dp+'%;width:12px;height:12px;background:#fff;border:2px solid #4a5568;border-radius:50%;transform:translateX(-50%)"></span>'
    +'</div><span style="font-size:10px;color:#a0aec0">R</span>'
    +'<span style="font-size:11px;color:#718096;margin-left:4px">'+blbl(b)+'</span>'
    +'</div></div>';
}}
function renderSlice(arr,el,off,pg){{
  var s=arr.slice(off,off+pg);
  s.forEach(function(a){{var d=document.createElement('div');d.innerHTML=card(a);el.appendChild(d.firstChild);}});
  return off+s.length;
}}
function updBtn(btn,arr,off,pg){{
  var r=arr.length-off;
  if(r>0){{btn.style.display='block';btn.textContent='Load '+Math.min(r,pg)+' more';}}
  else btn.style.display='none';
}}
window.tdLoad=function(w){{
  if(w==='sci'){{sciOff=renderSlice(sci,document.getElementById('td-sci-list'),sciOff,SCI_PG);updBtn(document.getElementById('td-sci-more'),sci,sciOff,SCI_PG);}}
  else{{wldOff=renderSlice(world,document.getElementById('td-world-list'),wldOff,WLD_PG);updBtn(document.getElementById('td-world-more'),world,wldOff,WLD_PG);}}
}};
fetch('/data/kd-articles.json').then(function(r){{return r.json();}}).then(function(data){{
  sci=data.filter(function(a){{return a.date===TODAY&&!!a.is_science;}}).sort(function(a,b){{return(b.n_sources||1)-(a.n_sources||1);}});
  world=data.filter(function(a){{return a.date===TODAY&&!a.is_science;}}).sort(function(a,b){{return(b.n_sources||1)-(a.n_sources||1);}});
  document.getElementById('td-sci-n').textContent=sci.length;
  document.getElementById('td-world-n').textContent=world.length;
  document.getElementById('td-count').textContent=sci.length+world.length;
  var snCnt={{space:0,animals:0,history:0,environment:0,technology:0}};
  sci.concat(world).forEach(function(a){{(a.cats||[]).forEach(function(c){{if(snCnt.hasOwnProperty(c))snCnt[c]++;}});}});
  document.getElementById('td-spc-n').textContent=snCnt.space;
  document.getElementById('td-ani-n').textContent=snCnt.animals;
  document.getElementById('td-his-n').textContent=snCnt.history;
  document.getElementById('td-env-n').textContent=snCnt.environment;
  document.getElementById('td-tec-n').textContent=snCnt.technology;
  if(snCnt.space+snCnt.animals+snCnt.history+snCnt.environment+snCnt.technology>0)
    document.getElementById('td-subcats').style.display='flex';
  if(!sci.length&&!world.length){{
    document.getElementById('td-empty').style.display='';
    document.getElementById('td-sci-sec').style.display='none';
    document.getElementById('td-world-sec').style.display='none';
  }}else{{
    document.getElementById('td-jump').style.display='flex';
    if(!sci.length)document.getElementById('td-sci-sec').style.display='none';
    else document.getElementById('td-sci-hdr').textContent=sci.length+' article'+(sci.length!==1?'s':'');
    if(!world.length)document.getElementById('td-world-sec').style.display='none';
    else document.getElementById('td-world-hdr').textContent=world.length+' article'+(world.length!==1?'s':'');
  }}
  sciOff=renderSlice(sci,document.getElementById('td-sci-list'),0,SCI_PG);
  updBtn(document.getElementById('td-sci-more'),sci,sciOff,SCI_PG);
  wldOff=renderSlice(world,document.getElementById('td-world-list'),0,WLD_PG);
  updBtn(document.getElementById('td-world-more'),world,wldOff,WLD_PG);
}}).catch(function(){{document.getElementById('td-empty').style.display='';}});
document.getElementById('today-search').addEventListener('input',function(){{
  var q=this.value.toLowerCase().trim();
  var sciEl=document.getElementById('td-sci-list'),wldEl=document.getElementById('td-world-list');
  if(!q){{
    sciEl.innerHTML='';wldEl.innerHTML='';
    sciOff=renderSlice(sci,sciEl,0,SCI_PG);updBtn(document.getElementById('td-sci-more'),sci,sciOff,SCI_PG);
    wldOff=renderSlice(world,wldEl,0,WLD_PG);updBtn(document.getElementById('td-world-more'),world,wldOff,WLD_PG);
    document.getElementById('td-sci-sec').style.display=sci.length?'':'none';
    document.getElementById('td-world-sec').style.display=world.length?'':'none';
    return;
  }}
  function match(a){{return((a.title||'')+' '+(a.description||'')).toLowerCase().indexOf(q)!==-1;}}
  var fs=sci.filter(match),fw=world.filter(match);
  sciEl.innerHTML='';fw&&(wldEl.innerHTML='');
  fs.forEach(function(a){{var d=document.createElement('div');d.innerHTML=card(a);sciEl.appendChild(d.firstChild);}});
  fw.forEach(function(a){{var d=document.createElement('div');d.innerHTML=card(a);wldEl.appendChild(d.firstChild);}});
  document.getElementById('td-sci-more').style.display='none';
  document.getElementById('td-world-more').style.display='none';
  document.getElementById('td-sci-sec').style.display=fs.length?'':'none';
  document.getElementById('td-world-sec').style.display=fw.length?'':'none';
}});
}})();
</script>
</body></html>"""

    upload("news/today.html", page, f"[scraper] Today's news — dynamic JS, {total_today} articles for {today}")
    print(f"  ✓ today.html (dynamic JS): {total_today} today ({len(sci_today)} sci, {len(world_today)} world)")


# ── Trending topics ───────────────────────────────────────────────────────────
def build_trending(manifest):
    """Return top 5 keyword clusters from recent article titles."""
    articles = manifest.get("articles", [])
    recent = sorted(articles, key=lambda x: x.get("date",""), reverse=True)[:15]
    SKIP = {"the","a","an","in","on","at","to","for","of","and","or","is","are",
            "was","were","be","has","have","had","will","would","it","this","that",
            "as","by","from","with","its","how","why","what","new","more","after",
            "they","says","over","amid","first","than","but","not","can","one","may",
            "two","about","could","news","year","years","using","found","study",
            "scientists","researchers","finds","discover","discovered","found"}
    freq = {}
    for a in recent:
        title = a.get("display_title", a.get("title","")).lower()
        for w in re.sub(r"[^\w\s]","",title).split():
            if w not in SKIP and len(w) > 3:
                freq[w] = freq.get(w, 0) + 1
    top = sorted(freq.items(), key=lambda x: -x[1])[:6]
    if not top:
        return ""
    _KW_TO_CAT = {
        "space": "/news/space.html", "nasa": "/news/space.html", "planet": "/news/space.html",
        "mars": "/news/space.html", "moon": "/news/space.html", "asteroid": "/news/space.html",
        "telescope": "/news/space.html", "galaxy": "/news/space.html", "rocket": "/news/space.html",
        "animals": "/news/animals.html", "animal": "/news/animals.html", "whale": "/news/animals.html",
        "shark": "/news/animals.html", "bird": "/news/animals.html", "fish": "/news/animals.html",
        "wolf": "/news/animals.html", "bear": "/news/animals.html", "coral": "/news/animals.html",
        "history": "/news/history.html", "ancient": "/news/history.html", "fossil": "/news/history.html",
        "dinosaur": "/news/history.html", "archaeology": "/news/history.html", "medieval": "/news/history.html",
        "environment": "/news/environment.html", "climate": "/news/environment.html",
        "ocean": "/news/environment.html", "forest": "/news/environment.html",
        "technology": "/news/technology.html", "robot": "/news/technology.html",
        "artificial": "/news/technology.html", "quantum": "/news/technology.html",
        "computer": "/news/technology.html", "drone": "/news/technology.html",
    }
    tags = " ".join(
        f'<a href="{_KW_TO_CAT.get(w, "/news/archive.html")}" style="background:#e2e8f0;color:#2d3748;padding:4px 10px;'
        f'border-radius:20px;font-size:12px;text-decoration:none;font-family:system-ui">'
        f'{w}</a>'
        for w, _ in top
    )
    return (
        '<div style="margin:16px 0 8px;padding:12px 16px;background:#fffbeb;border:1px solid #fef3c7;border-radius:8px">'
        '<p style="font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#92400e;margin:0 0 8px">Trending this week</p>'
        f'<div style="display:flex;flex-wrap:wrap;gap:6px">{tags}</div>'
        '</div>'
    )


# ── Public articles JSON (used by related-articles JS on every article page) ──
def generate_articles_json(manifest):
    articles = manifest.get("articles", [])
    data = [
        {
            "slug":        a["slug"],
            "title":       a.get("display_title", a.get("title", "")),
            "date":        a.get("date", ""),
            "is_science":  a.get("is_science", False),
            "bias_avg":    a.get("bias_avg", 0.0),
            "n_sources":   a.get("n_sources", 1),
            "description": a.get("description", "")[:200],
            "cats":        _article_cats(a),
        }
        for a in sorted(articles, key=lambda x: x.get("date", ""), reverse=True)
    ]
    upload("data/kd-articles.json", json.dumps(data, ensure_ascii=False), f"[scraper] Articles index ({len(data)} items)")
    print(f"  Articles JSON: {len(data)} items")


# ── Daily digest page ──────────────────────────────────────────────────────────
def generate_daily_digest(manifest, today):
    articles = manifest.get("articles", [])
    todays = [a for a in articles if a.get("date") == today]
    n_today = len(todays)
    if not todays:
        print("  Digest: no articles for today, skipping")
        return

    # Dynamic JS shell — fetches /data/kd-articles.json at runtime and filters to today
    # Keeps dated digest pages at ~9KB instead of 200-300KB for high-activity days
    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>KiddieDaily — {today} Daily Digest</title>
<meta name="description" content="KiddieDaily daily digest for {today} — kid-safe, bias-rated news for families.">
<meta property="og:title" content="KiddieDaily Daily Digest — {today}">
<meta property="og:description" content="Today's kid-friendly news — bias-rated and fact-check linked.">
<meta property="og:url" content="https://kiddiedaily.com/digest/{today}.html">
<meta property="og:image" content="https://kiddiedaily.com/og-science.svg">
<meta name="twitter:card" content="summary">
<link rel="canonical" href="https://kiddiedaily.com/digest/{today}.html">
<link rel="alternate" type="application/rss+xml" title="KiddieDaily RSS" href="/feed.xml">
{CSS}
<style>
.dig-card{{background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:14px 18px 10px;margin:8px 0;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.dig-card h3{{margin:0 0 4px;font-size:15px}}
.dig-card h3 a{{color:#1a4d80;text-decoration:none}}
.dig-card h3 a:hover{{text-decoration:underline}}
.dig-meta{{font-size:12px;color:#718096;font-family:system-ui,sans-serif}}
.dig-sci{{border-left:3px solid #059669}}
.dig-world{{border-left:3px solid #1d4ed8}}
.dig-section-hdr{{font-size:18px;font-weight:700;margin:24px 0 10px;padding-bottom:6px;font-family:system-ui,sans-serif}}
.dig-section-hdr.sci{{color:#065f46;border-bottom:2px solid #d1fae5}}
.dig-section-hdr.world{{color:#1e40af;border-bottom:2px solid #dbeafe}}
#dig-count{{font-size:14px;color:#718096;font-family:system-ui,sans-serif;margin:0 0 16px;min-height:20px}}
</style>
</head><body>
{HEADER}
<main id="main">
<h1 style="font-size:28px;margin-bottom:4px">Daily Digest</h1>
<p style="color:#718096;font-family:system-ui,sans-serif;font-size:14px;margin:0 0 16px">{today}</p>

<p id="dig-count">Loading today's stories…</p>

<div id="dig-science-wrap" style="display:none">
  <h2 class="dig-section-hdr sci" id="dig-sci-hdr"></h2>
  <div id="dig-science-list"></div>
  <div style="text-align:center;margin:12px 0 4px">
    <button id="dig-sci-more" onclick="digLoadSci()" style="display:none;background:#065f46;color:#fff;border:none;padding:9px 24px;border-radius:6px;font-size:13px;cursor:pointer;font-family:system-ui,sans-serif">Load more</button>
  </div>
</div>

<div id="dig-world-wrap" style="display:none">
  <h2 class="dig-section-hdr world" id="dig-world-hdr"></h2>
  <div id="dig-world-list"></div>
  <div style="text-align:center;margin:12px 0 4px">
    <button id="dig-world-more" onclick="digLoadWorld()" style="display:none;background:#1e40af;color:#fff;border:none;padding:9px 24px;border-radius:6px;font-size:13px;cursor:pointer;font-family:system-ui,sans-serif">Load more</button>
  </div>
</div>

<p id="dig-empty" style="display:none;color:#718096;font-family:system-ui,sans-serif;font-size:14px">
  No articles for this date yet. Check back after the daily update.
</p>

<div style="margin-top:24px;padding:14px 16px;background:#f7fafc;border-left:4px solid #1a4d80;border-radius:0 8px 8px 0;font-family:system-ui,sans-serif;font-size:13px;color:#4a5568;display:none" id="dig-legend">
  <strong>Bias scale:</strong> -2 = far left &nbsp;|&nbsp; 0 = center &nbsp;|&nbsp; +2 = far right.
  Sources = how many of our monitored outlets covered the same story.
</div>

<p style="text-align:center;margin-top:32px;font-size:13px;color:#718096;font-family:system-ui,sans-serif">
  <a href="/news/" style="color:#1a4d80">All news</a> &middot;
  <a href="/digest/weekly.html" style="color:#1a4d80">Weekly digest</a> &middot;
  <a href="/news/archive.html" style="color:#1a4d80">Archive</a> &middot;
  <a href="/feed.xml" style="color:#1a4d80">RSS</a>
</p>
</main>
{FOOTER}

<script>
(function() {{
  var TARGET_DATE = '{today}';
  var PAGE = 20;
  var sci = [], world = [], sciOff = 0, worldOff = 0;

  function biasLabel(b) {{
    if (b <= -1.2) return 'Far Left';
    if (b <= -0.4) return 'Leans Left';
    if (b <= -0.15) return 'Center-Left';
    if (b <= 0.15) return 'Center';
    if (b <= 0.4) return 'Center-Right';
    if (b <= 1.2) return 'Leans Right';
    return 'Far Right';
  }}

  function card(a, cls) {{
    var n = a.n_sources || 1;
    var bias = typeof a.bias_avg === 'number' ? a.bias_avg : 0;
    var sign = bias >= 0 ? '+' : '';
    var desc = a.description ? '<p style="font-size:13px;color:#4a5568;margin:4px 0 0;line-height:1.5">' + a.description.slice(0,130) + (a.description.length > 130 ? '…' : '') + '</p>' : '';
    var cats=(a.cats||[]).filter(function(c){{return c!=='science'&&c!=='world';}});
    var catTags=cats.slice(0,2).map(function(c){{return '<span style="font-size:9px;background:#e0e7ff;color:#3730a3;padding:1px 5px;border-radius:20px;font-weight:600;margin-right:4px">'+c+'</span>';}}).join('');
    var mainBadge='<span style="font-size:9px;font-weight:700;padding:2px 7px;border-radius:20px;margin-right:6px;'+(a.is_science?'background:#d1fae5;color:#065f46':'background:#dbeafe;color:#1e40af')+'">'+(a.is_science?'Science':'World News')+'</span>';
    return '<div class="dig-card ' + cls + '">'
      + '<div style="margin-bottom:5px">'+mainBadge+catTags+'</div>'
      + '<h3><a href="/' + a.slug + '">' + (a.display_title || a.title) + '</a></h3>'
      + desc
      + '<p class="dig-meta">' + n + ' source' + (n !== 1 ? 's' : '') + ' &middot; Bias: ' + biasLabel(bias) + ' (' + sign + bias.toFixed(1) + ')</p>'
      + '</div>';
  }}

  function renderSlice(arr, el, off, cls) {{
    var slice = arr.slice(off, off + PAGE);
    slice.forEach(function(a) {{
      var div = document.createElement('div');
      div.innerHTML = card(a, cls);
      el.appendChild(div.firstChild);
    }});
    return off + slice.length;
  }}

  function updateBtn(btn, arr, off) {{
    var rem = arr.length - off;
    if (rem > 0) {{
      btn.style.display = 'block';
      btn.textContent = 'Load ' + Math.min(rem, PAGE) + ' more';
    }} else {{
      btn.style.display = 'none';
    }}
  }}

  fetch('/data/kd-articles.json')
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
      var all = Array.isArray(data) ? data : (data.articles || []);
      var todays = all.filter(function(a) {{ return a.date === TARGET_DATE; }});

      var countEl   = document.getElementById('dig-count');
      var emptyEl   = document.getElementById('dig-empty');
      var sciWrap   = document.getElementById('dig-science-wrap');
      var worldWrap = document.getElementById('dig-world-wrap');
      var sciHdr    = document.getElementById('dig-sci-hdr');
      var worldHdr  = document.getElementById('dig-world-hdr');
      var sciEl     = document.getElementById('dig-science-list');
      var worldEl   = document.getElementById('dig-world-list');
      var sciBtn    = document.getElementById('dig-sci-more');
      var worldBtn  = document.getElementById('dig-world-more');
      var legendEl  = document.getElementById('dig-legend');

      if (!todays.length) {{
        countEl.style.display = 'none';
        emptyEl.style.display = 'block';
        return;
      }}

      sci   = todays.filter(function(a) {{ return a.is_science; }});
      world = todays.filter(function(a) {{ return !a.is_science; }});

      countEl.textContent = todays.length + ' stories for ' + TARGET_DATE;
      legendEl.style.display = 'block';

      if (sci.length) {{
        sciHdr.textContent = 'Science (' + sci.length + ' ' + (sci.length === 1 ? 'story' : 'stories') + ')';
        sciOff = renderSlice(sci, sciEl, 0, 'dig-sci');
        updateBtn(sciBtn, sci, sciOff);
        sciWrap.style.display = 'block';
      }}
      if (world.length) {{
        worldHdr.textContent = 'World News (' + world.length + ' ' + (world.length === 1 ? 'story' : 'stories') + ')';
        worldOff = renderSlice(world, worldEl, 0, 'dig-world');
        updateBtn(worldBtn, world, worldOff);
        worldWrap.style.display = 'block';
      }}
    }})
    .catch(function() {{
      document.getElementById('dig-count').textContent = 'Could not load today\'s stories. Please try refreshing.';
    }});

  window.digLoadSci = function() {{
    sciOff = renderSlice(sci, document.getElementById('dig-science-list'), sciOff, 'dig-sci');
    updateBtn(document.getElementById('dig-sci-more'), sci, sciOff);
  }};
  window.digLoadWorld = function() {{
    worldOff = renderSlice(world, document.getElementById('dig-world-list'), worldOff, 'dig-world');
    updateBtn(document.getElementById('dig-world-more'), world, worldOff);
  }};
}})();
</script>
</body></html>"""

    upload(f"digest/{today}.html", page, f"[scraper] Daily digest {today} (dynamic) — {n_today} articles")
    # Also write /digest/latest.html as a redirect to today's digest
    redirect = f"""<!DOCTYPE html><html><head>
<meta http-equiv="refresh" content="0;url=/digest/{today}.html">
<title>KiddieDaily Latest Digest</title>
</head><body>
<p>Redirecting to <a href="/digest/{today}.html">today's digest</a>...</p>
</body></html>"""
    upload("digest/latest.html", redirect, f"[scraper] Update latest digest redirect → {today}")
    print(f"  Digest: {n_today} articles for {today} (dynamic JS render)")


# ── Weekly digest page ────────────────────────────────────────────────────────
def generate_weekly_digest(manifest, today):
    from datetime import timedelta
    articles = manifest.get("articles", [])
    cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    week_articles = [a for a in articles if a.get("date", "") >= cutoff]
    total_week = len(week_articles)
    if not week_articles:
        print("  Weekly digest: no articles in last 7 days, skipping")
        return

    # Lightweight dynamic shell — loads from /data/kd-articles.json at runtime
    # (same approach as archive page — reduces file from 300KB+ to ~9KB)
    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>KiddieDaily Weekly Digest — Best of the Week</title>
<meta name="description" content="KiddieDaily weekly digest — {total_week} stories from the last 7 days for families. Kid-safe, bias-rated news.">
<meta property="og:title" content="KiddieDaily — Best of the Week">
<meta property="og:description" content="{total_week} kid-friendly stories from the last 7 days — bias-rated and fact-check linked.">
<meta property="og:url" content="https://kiddiedaily.com/digest/weekly.html">
<meta property="og:image" content="https://kiddiedaily.com/og-science.svg">
<meta name="twitter:card" content="summary">
<link rel="canonical" href="https://kiddiedaily.com/digest/weekly.html">
<link rel="alternate" type="application/rss+xml" title="KiddieDaily RSS" href="/feed.xml">
{CSS}
<style>
.wk-card{{background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:14px 18px 10px;margin:8px 0;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.wk-card h3{{margin:0 0 4px;font-size:15px}}
.wk-card h3 a{{color:#1a4d80;text-decoration:none}}
.wk-card h3 a:hover{{text-decoration:underline}}
.wk-meta{{font-size:12px;color:#718096;font-family:system-ui,sans-serif}}
.wk-sci{{border-left:3px solid #059669}}
.wk-world{{border-left:3px solid #1d4ed8}}
.wk-section-hdr{{font-size:18px;font-weight:700;margin:28px 0 10px;padding-bottom:6px;font-family:system-ui,sans-serif}}
.wk-section-hdr.sci{{color:#065f46;border-bottom:2px solid #d1fae5}}
.wk-section-hdr.world{{color:#1e40af;border-bottom:2px solid #dbeafe}}
#wk-bias-bar{{padding:12px 16px;background:#f7fafc;border-left:4px solid #1a4d80;border-radius:0 8px 8px 0;font-family:system-ui,sans-serif;font-size:13px;color:#4a5568;margin-bottom:20px;display:none}}
#wk-count{{font-size:14px;color:#718096;font-family:system-ui,sans-serif;margin:0 0 16px;min-height:20px}}
</style>
</head><body>
{HEADER}
<main id="main">
<h1 style="font-size:28px;margin-bottom:4px">Best of the Week</h1>
<p style="color:#718096;font-family:system-ui,sans-serif;font-size:14px;margin:0 0 16px">
  Last 7 days &middot; Updated {today}
</p>

<div id="wk-bias-bar"></div>
<p id="wk-count">Loading this week's stories…</p>

<div id="wk-science-wrap" style="display:none">
  <h2 class="wk-section-hdr sci" id="wk-sci-hdr"></h2>
  <div id="wk-science-list"></div>
</div>

<div id="wk-world-wrap" style="display:none">
  <h2 class="wk-section-hdr world" id="wk-world-hdr"></h2>
  <div id="wk-world-list"></div>
</div>

<p id="wk-empty" style="display:none;color:#718096;font-family:system-ui,sans-serif;font-size:14px">
  No articles found for this week yet — check back after the daily update.
</p>

<p style="text-align:center;margin-top:32px;font-size:13px;color:#718096;font-family:system-ui,sans-serif">
  <a href="/news/" style="color:#1a4d80">All news</a> &middot;
  <a href="/digest/latest.html" style="color:#1a4d80">Today's digest</a> &middot;
  <a href="/news/archive.html" style="color:#1a4d80">Full archive</a> &middot;
  <a href="/feed.xml" style="color:#1a4d80">RSS</a>
</p>
</main>
{FOOTER}

<script>
(function() {{
  var cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - 7);
  var cutoffStr = cutoff.toISOString().slice(0, 10);
  var MO=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  function fmtDate(d){{var p=d?d.split('-'):[];return p.length===3?MO[parseInt(p[1])-1]+' '+parseInt(p[2])+', '+p[0]:d||'';}}

  function biasLabel(b) {{
    if (b <= -1.2) return 'Far Left';
    if (b <= -0.4) return 'Leans Left';
    if (b <= -0.15) return 'Center-Left';
    if (b <= 0.15) return 'Center';
    if (b <= 0.4) return 'Center-Right';
    if (b <= 1.2) return 'Leans Right';
    return 'Far Right';
  }}

  function card(a, cls) {{
    var n = a.n_sources || 1;
    var bias = typeof a.bias_avg === 'number' ? a.bias_avg : 0;
    var bLabel = biasLabel(bias);
    var sign = bias >= 0 ? '+' : '';
    var desc = a.description ? '<p style="font-size:13px;color:#4a5568;margin:4px 0 0;line-height:1.5">' + a.description.slice(0,130) + (a.description.length > 130 ? '…' : '') + '</p>' : '';
    var cats=(a.cats||[]).filter(function(c){{return c!=='science'&&c!=='world';}});
    var catTags=cats.slice(0,2).map(function(c){{return '<span style="font-size:9px;background:#e0e7ff;color:#3730a3;padding:1px 5px;border-radius:20px;font-weight:600;margin-right:4px">'+c+'</span>';}}).join('');
    var mainBadge='<span style="font-size:9px;font-weight:700;padding:2px 7px;border-radius:20px;margin-right:6px;'+(a.is_science?'background:#d1fae5;color:#065f46':'background:#dbeafe;color:#1e40af')+'">'+(a.is_science?'Science':'World News')+'</span>';
    return '<div class="wk-card ' + cls + '">'
      + '<div style="margin-bottom:5px">'+mainBadge+catTags+'</div>'
      + '<h3><a href="/' + a.slug + '">' + (a.display_title || a.title) + '</a></h3>'
      + desc
      + '<p class="wk-meta">' + fmtDate(a.date) + ' &middot; ' + n + ' source' + (n !== 1 ? 's' : '') + ' &middot; Bias: ' + bLabel + ' (' + sign + bias.toFixed(1) + ')</p>'
      + '</div>';
  }}

  fetch('/data/kd-articles.json')
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
      var all = Array.isArray(data) ? data : (data.articles || []);
      var week = all.filter(function(a) {{ return (a.date || '') >= cutoffStr; }});

      var sciEl   = document.getElementById('wk-science-list');
      var worldEl = document.getElementById('wk-world-list');
      var sciWrap = document.getElementById('wk-science-wrap');
      var worldWrap = document.getElementById('wk-world-wrap');
      var sciHdr  = document.getElementById('wk-sci-hdr');
      var worldHdr= document.getElementById('wk-world-hdr');
      var countEl = document.getElementById('wk-count');
      var biasBar = document.getElementById('wk-bias-bar');
      var emptyEl = document.getElementById('wk-empty');

      if (!week.length) {{
        countEl.style.display = 'none';
        emptyEl.style.display = 'block';
        return;
      }}

      week.sort(function(a, b) {{ return (b.date || '') < (a.date || '') ? -1 : 1; }});
      var sci   = week.filter(function(a) {{ return a.is_science; }});
      var world = week.filter(function(a) {{ return !a.is_science; }});

      // Bias summary
      var biases = week.map(function(a) {{ return typeof a.bias_avg === 'number' ? a.bias_avg : 0; }});
      var avg = biases.reduce(function(s, v) {{ return s + v; }}, 0) / biases.length;
      var sign = avg >= 0 ? '+' : '';
      biasBar.innerHTML = '<strong>Week bias summary:</strong> Average across all stories this week is <strong>' + sign + avg.toFixed(2) + '</strong> (' + biasLabel(avg) + '). Scale: -2 = far left | 0 = center | +2 = far right.';
      biasBar.style.display = 'block';

      countEl.textContent = week.length + ' stories from the last 7 days';

      if (sci.length) {{
        sciHdr.textContent = 'Science (' + sci.length + ' ' + (sci.length === 1 ? 'story' : 'stories') + ')';
        sciEl.innerHTML = sci.map(function(a) {{ return card(a, 'wk-sci'); }}).join('');
        sciWrap.style.display = 'block';
      }}
      if (world.length) {{
        worldHdr.textContent = 'World News (' + world.length + ' ' + (world.length === 1 ? 'story' : 'stories') + ')';
        worldEl.innerHTML = world.map(function(a) {{ return card(a, 'wk-world'); }}).join('');
        worldWrap.style.display = 'block';
      }}
    }})
    .catch(function() {{
      document.getElementById('wk-count').textContent = 'Could not load this week’s stories. Please try refreshing.';
    }});
}})();
</script>
</body></html>"""

    upload("digest/weekly.html", page, f"[scraper] Weekly digest (dynamic) — {total_week} articles this week")
    print(f"  Weekly digest: {total_week} articles over 7 days (dynamic JS render)")


# ── Search page ──────────────────────────────────────────────────────────────
def generate_for_parents_page(manifest, today):
    """Generate /parents/index.html — daily parent briefing with bias context and discussion guides."""
    articles = manifest.get("articles", [])
    today_articles = sorted(
        [a for a in articles if a.get("date") == today],
        key=lambda x: -(x.get("n_sources", 1) * 2 + (5 if x.get("is_science") else 0))
    )
    total = len(articles)
    sci_count = sum(1 for a in articles if a.get("is_science"))
    sci_pct = round(sci_count / total * 100) if total else 0
    all_biases = [a.get("bias_avg", 0.0) for a in articles]
    avg_bias = sum(all_biases) / len(all_biases) if all_biases else 0.0
    left_n   = sum(1 for b in all_biases if b < -0.3)
    center_n = sum(1 for b in all_biases if -0.3 <= b <= 0.3)
    right_n  = sum(1 for b in all_biases if b > 0.3)
    avg_bias_lbl = ("Center" if abs(avg_bias) < 0.3
                    else ("Left-leaning" if avg_bias < 0 else "Right-leaning"))

    stop = {"about", "their", "these", "those", "would", "could", "which", "where",
            "there", "after", "other", "first", "world", "using", "study", "finds",
            "found", "shows", "says", "that", "have", "with", "from", "this", "will"}

    def _card(a):
        slug     = a["slug"]
        title    = a.get("display_title", a.get("title", ""))
        is_sci   = a.get("is_science", False)
        n        = a.get("n_sources", 1)
        bias     = a.get("bias_avg", 0.0)
        bias_lbl = "Center" if abs(bias) < 0.3 else ("Left-leaning" if bias < 0 else "Right-leaning")
        dot_pct  = max(5, min(95, round((bias + 2) / 4 * 100)))
        badge_cls = "kd-badge-sci" if is_sci else "kd-badge-news"
        badge_lbl = "Science" if is_sci else "World News"
        words = [w for w in re.sub(r"[^\w\s]", "", title.lower()).split()
                 if len(w) > 3 and w not in stop]
        topic = " ".join(words[:2]) if len(words) >= 2 else (words[0] if words else "this")
        teaser = (f"Ask your child: &ldquo;What do scientists think about <em>{topic}</em>?&rdquo;"
                  if is_sci else
                  f"Ask: &ldquo;Why might people disagree about <em>{topic}</em>?&rdquo;")
        return (
            f'<div style="background:#fff;border:1px solid #dde4ef;border-radius:10px;'
            f'padding:16px 20px;margin:10px 0;box-shadow:0 1px 4px rgba(0,0,0,.05)">'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap">'
            f'<span class="kd-badge {badge_cls}">{badge_lbl}</span>'
            f'<span style="font-size:12px;color:#718096">{n} source{"s" if n!=1 else ""}'
            f' &middot; {bias_lbl} ({bias:+.1f})</span></div>'
            f'<h3 style="margin:0 0 8px;font-size:16px;line-height:1.4">'
            f'<a href="/{slug}" style="color:#1a4d80;text-decoration:none">{title}</a></h3>'
            f'<div style="display:flex;align-items:center;gap:6px;margin-bottom:10px">'
            f'<span style="font-size:11px;font-weight:700;color:#718096;width:14px">L</span>'
            f'<div style="flex:1;height:6px;border-radius:3px;'
            f'background:linear-gradient(to right,#3182ce,#805ad5,#e53e3e);position:relative">'
            f'<span style="position:absolute;top:-5px;left:{dot_pct}%;width:16px;height:16px;'
            f'background:#fff;border:2px solid #4a5568;border-radius:50%;transform:translateX(-50%)"></span>'
            f'</div><span style="font-size:11px;font-weight:700;color:#718096;width:14px;text-align:right">R</span></div>'
            f'<div style="background:#f7fafc;border-radius:6px;padding:8px 12px;font-size:13px;color:#4a5568">'
            f'&#128172; {teaser} '
            f'<a href="/{slug}" style="color:#1a4d80;font-size:12px">Full article + discussion guide &rarr;</a>'
            f'</div></div>'
        )

    cards_html = "\n".join(_card(a) for a in today_articles[:8])
    n_today = len(today_articles)

    # Subcategory breakdown for today
    _SUBCAT_META = [
        ("space",       "&#x1f680;", "Space"),
        ("animals",     "&#x1f43e;", "Animals"),
        ("history",     "&#x1f3db;", "History"),
        ("environment", "&#x1f33f;", "Environment"),
        ("technology",  "&#x1f4bb;", "Technology"),
    ]
    subcat_counts = {}
    for a in today_articles:
        for c in (a.get("cats") or []):
            if c in {k for k, _, _ in _SUBCAT_META}:
                subcat_counts[c] = subcat_counts.get(c, 0) + 1
    subcat_chips = "".join(
        f'<a href="/news/{key}.html" style="display:inline-flex;align-items:center;gap:5px;'
        f'background:#f7fafc;border:1px solid #e2e8f0;border-radius:20px;padding:5px 12px;'
        f'font-size:13px;color:#2d3748;text-decoration:none;font-family:system-ui,sans-serif">'
        f'{icon} <strong>{label}</strong> <span style="color:#718096">{subcat_counts.get(key,0)}</span></a>'
        for key, icon, label in _SUBCAT_META if subcat_counts.get(key, 0) > 0
    )
    subcat_html = (
        f'<div class="section-hdr">Today\'s topics</div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:8px;margin:0 0 24px">{subcat_chips}</div>'
    ) if subcat_chips else ""

    # Source distribution bar
    bar_total = left_n + center_n + right_n or 1
    left_pct   = round(left_n / bar_total * 100)
    center_pct = round(center_n / bar_total * 100)
    right_pct  = 100 - left_pct - center_pct

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>For Parents — KiddieDaily Daily Briefing</title>
<meta name="description" content="KiddieDaily parent briefing for {today}: {n_today} articles, bias ratings, source analysis, and discussion guides for families.">
<meta property="og:title" content="KiddieDaily — For Parents ({today})">
<meta property="og:description" content="{n_today} articles today, bias-rated from 36 sources. Discussion guides included.">
<meta property="og:image" content="https://kiddiedaily.com/og-science.svg">
<meta property="og:url" content="https://kiddiedaily.com/parents/">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="https://kiddiedaily.com/parents/">
<link rel="alternate" type="application/rss+xml" title="KiddieDaily RSS" href="/feed.xml">
{CSS}
<style>
.stat-row{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:16px 0 24px}}
.stat-box{{background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:14px 16px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.05)}}
.stat-box .val{{font-size:28px;font-weight:700;color:#1a4d80;display:block;margin-bottom:2px}}
.stat-box .lbl{{font-size:12px;color:#718096;font-family:system-ui,sans-serif}}
.step-row{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:16px 0}}
.step-box{{background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:14px 16px}}
.step-box .num{{font-size:22px;font-weight:700;color:#1e40af;margin-bottom:4px}}
.step-box p{{margin:0;font-size:14px;color:#1e40af;line-height:1.5}}
.section-hdr{{font-size:11px;font-weight:700;color:#718096;text-transform:uppercase;letter-spacing:1.2px;margin:28px 0 10px;font-family:system-ui,sans-serif}}
.kd-badge{{font-size:10px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;padding:2px 8px;border-radius:20px}}
.kd-badge-sci{{background:#d1fae5;color:#065f46}}
.kd-badge-news{{background:#dbeafe;color:#1e40af}}
</style>
</head><body>
{HEADER}
<main id="main" style="max-width:780px;margin:0 auto;padding:32px 24px 64px">
<h1 style="font-size:28px;margin:0 0 4px">For Parents</h1>
<p style="color:#718096;font-family:system-ui,sans-serif;font-size:15px;margin:0 0 20px">
Your daily briefing — {today} &middot; Balanced sources &middot; No spin &middot; Made for families
</p>

<div class="stat-row">
  <div class="stat-box"><span class="val">{n_today}</span><span class="lbl">Stories today</span></div>
  <div class="stat-box"><span class="val">{sci_pct}%</span><span class="lbl">Science content</span></div>
  <div class="stat-box"><span class="val">{total}</span><span class="lbl">Total in archive</span></div>
  <div class="stat-box"><span class="val">{avg_bias:+.2f}</span><span class="lbl">Avg bias (all time)</span></div>
</div>

<div style="background:#fff8e1;border:1px solid #fde68a;border-radius:10px;padding:16px 20px;margin:0 0 24px;font-family:system-ui,sans-serif">
<div style="font-size:11px;font-weight:700;color:#92400e;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">&#128200; Source balance across all articles</div>
<div style="display:flex;height:24px;border-radius:6px;overflow:hidden;margin-bottom:6px">
  <div style="width:{left_pct}%;background:#3182ce;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff">{left_pct if left_pct>8 else ""}%</div>
  <div style="width:{center_pct}%;background:#805ad5;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff">{center_pct if center_pct>8 else ""}%</div>
  <div style="width:{right_pct}%;background:#e53e3e;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff">{right_pct if right_pct>8 else ""}%</div>
</div>
<div style="display:flex;gap:16px;font-size:12px;color:#92400e">
  <span>&#9632; Left-leaning: {left_n}</span>
  <span>&#9632; Center: {center_n}</span>
  <span>&#9632; Right-leaning: {right_n}</span>
  <span style="margin-left:auto;font-weight:600">Overall: {avg_bias_lbl} ({avg_bias:+.2f})</span>
</div>
</div>

<div class="section-hdr">How to use KiddieDaily with your family</div>
<div class="step-row">
  <div class="step-box"><div class="num">1</div><p><strong>Read the bias bar.</strong> Every article shows which outlets covered it and whether they lean left, center, or right. No single outlet is always wrong — or always right.</p></div>
  <div class="step-box"><div class="num">2</div><p><strong>Use the discussion guide.</strong> Each article has 3 parent-specific prompts — what to ask your child, how to check facts, and how to explore further.</p></div>
  <div class="step-box"><div class="num">3</div><p><strong>Compare sources.</strong> When 2+ outlets cover the same story, we show you how each framed it. Look for what facts they agree on vs. what they emphasize differently.</p></div>
</div>

{subcat_html}<div class="section-hdr">Today&#39;s stories — {today}</div>
{cards_html if cards_html else '<p style="color:#718096;font-family:system-ui,sans-serif">No articles for today yet — check back after 6am ET when the scraper runs.</p>'}

<div style="background:#f0f4f8;border-radius:10px;padding:20px 24px;margin:28px 0 0;font-family:system-ui,sans-serif">
<div style="font-size:11px;font-weight:700;color:#4a5568;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px">Understanding bias ratings</div>
<div style="font-size:14px;color:#2d3748;line-height:1.6">
<p style="margin:0 0 8px">KiddieDaily uses <strong>AllSides</strong> and <strong>Ad Fontes Media</strong> bias ratings — the same methodology used by researchers and journalism schools.</p>
<p style="margin:0 0 8px">Scale: <strong>-2</strong> = far left &nbsp;|&nbsp; <strong>-1</strong> = leans left &nbsp;|&nbsp; <strong>0</strong> = center &nbsp;|&nbsp; <strong>+1</strong> = leans right &nbsp;|&nbsp; <strong>+2</strong> = far right</p>
<p style="margin:0">No media source is perfectly neutral. Our goal is to show you the landscape — so you can read with your eyes open and form your own family&#39;s view.</p>
</div>
</div>

<div style="margin-top:24px;display:flex;gap:10px;flex-wrap:wrap">
<a href="/news/today.html" style="background:#1a4d80;color:#fff;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Today&#39;s news</a>
<a href="/digest/latest.html" style="background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Daily digest</a>
<a href="/parent-zone/" style="background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Parent Zone</a>
<a href="/search.html" style="background:#f7fafc;color:#718096;border:1px solid #e2e8f0;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Search all</a>
<a href="/feed.xml" style="background:#f7fafc;color:#718096;border:1px solid #e2e8f0;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">RSS</a>
</div>
</main>
{FOOTER}
</body></html>"""

    upload("parents/index.html", page, f"[scraper] For-Parents briefing {today} — {n_today} articles, {avg_bias_lbl}")
    print(f"  For-Parents page: {n_today} articles today, avg bias {avg_bias:+.2f} ({avg_bias_lbl})")


def generate_subscribe_page(manifest, today):
    """Generate /subscribe/index.html — how to get daily KiddieDaily updates."""
    articles = manifest.get("articles", [])
    total = len(articles)

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Subscribe — Get Daily KiddieDaily Updates</title>
<meta name="description" content="Get daily KiddieDaily updates via RSS, email, or bookmark. Free, kid-safe news for families — no ads, no spin.">
<meta property="og:title" content="Subscribe — KiddieDaily">
<meta property="og:description" content="Free daily kid-safe news. RSS, bookmark, or daily digest — your choice. No ads, no spin.">
<meta property="og:url" content="https://kiddiedaily.com/subscribe/">
<meta name="twitter:card" content="summary">
<link rel="canonical" href="https://kiddiedaily.com/subscribe/">
<link rel="alternate" type="application/rss+xml" title="KiddieDaily RSS" href="/feed.xml">
{CSS}
<style>
.sub-card{{background:#fff;border:1px solid #dde4ef;border-radius:12px;padding:22px 24px;margin:12px 0;box-shadow:0 1px 4px rgba(0,0,0,.05);display:flex;gap:18px;align-items:flex-start}}
.sub-card .icon{{font-size:36px;min-width:44px;text-align:center}}
.sub-card h3{{margin:0 0 6px;font-size:17px;color:#1a4d80}}
.sub-card p{{margin:0;font-size:14px;color:#4a5568;line-height:1.55}}
.sub-card .action{{margin-top:12px}}
.sub-badge{{display:inline-block;font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px;letter-spacing:.8px;text-transform:uppercase;margin-left:6px}}
.badge-free{{background:#d1fae5;color:#065f46}}
.badge-soon{{background:#fef3c7;color:#92400e}}
</style>
</head><body>
{HEADER}
<main id="main" style="max-width:720px;margin:0 auto;padding:32px 24px 64px">
<h1 style="font-size:28px;margin:0 0 6px">Stay Updated</h1>
<p style="color:#718096;font-family:system-ui,sans-serif;font-size:15px;margin:0 0 24px">
KiddieDaily publishes fresh kid-safe, bias-rated news every morning at <strong>6am ET</strong>. Here&#39;s how to get it.
</p>

<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:14px 20px;margin:0 0 20px;font-family:system-ui,sans-serif">
<span style="font-size:13px;color:#1e40af">&#128202; <strong>{total} articles</strong> published so far &middot; updated daily &middot; free forever &middot; no ads &middot; no tracking</span>
</div>

<div class="sub-card">
<div class="icon">&#128231;</div>
<div>
<h3>RSS Feed <span class="sub-badge badge-free">Free · Live now</span></h3>
<p>The fastest way to follow KiddieDaily. Copy the feed URL into any RSS reader — Feedly, Apple News, Google News, Reeder, or any other reader you prefer.</p>
<div class="action" style="display:flex;flex-direction:column;gap:8px">
<div style="background:#f7fafc;border:1px solid #e2e8f0;border-radius:6px;padding:10px 14px;font-family:monospace;font-size:14px;color:#1a4d80;word-break:break-all">https://kiddiedaily.com/feed.xml</div>
<div style="display:flex;gap:8px;flex-wrap:wrap">
<a href="/feed.xml" style="background:#1a4d80;color:#fff;padding:8px 16px;border-radius:6px;font-size:13px;text-decoration:none;font-family:system-ui,sans-serif">Open RSS feed</a>
<a href="https://feedly.com/i/subscription/feed/https://kiddiedaily.com/feed.xml" rel="noopener nofollow" target="_blank" style="background:#2d8a3e;color:#fff;padding:8px 16px;border-radius:6px;font-size:13px;text-decoration:none;font-family:system-ui,sans-serif">Add to Feedly</a>
</div>
<p style="font-size:12px;color:#718096;margin:4px 0 0"><strong>How to use:</strong> In any RSS app, tap "Add feed" and paste the URL above. New articles appear automatically each morning.</p>
<details style="margin-top:10px;cursor:pointer">
<summary style="font-size:13px;font-weight:600;color:#1a4d80;list-style:none">&#9654; Browse by topic — individual category feeds</summary>
<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:10px">
<a href="/feed/science.xml" style="display:inline-flex;align-items:center;gap:4px;background:#d1fae5;color:#065f46;padding:5px 12px;border-radius:20px;font-size:12px;font-weight:600;text-decoration:none;font-family:system-ui,sans-serif">&#x1f52c; Science RSS</a>
<a href="/feed/world.xml" style="display:inline-flex;align-items:center;gap:4px;background:#dbeafe;color:#1e40af;padding:5px 12px;border-radius:20px;font-size:12px;font-weight:600;text-decoration:none;font-family:system-ui,sans-serif">&#x1f30d; World RSS</a>
<a href="/feed/space.xml" style="display:inline-flex;align-items:center;gap:4px;background:#ede9fe;color:#5b21b6;padding:5px 12px;border-radius:20px;font-size:12px;font-weight:600;text-decoration:none;font-family:system-ui,sans-serif">&#x1f680; Space RSS</a>
<a href="/feed/animals.xml" style="display:inline-flex;align-items:center;gap:4px;background:#fef3c7;color:#92400e;padding:5px 12px;border-radius:20px;font-size:12px;font-weight:600;text-decoration:none;font-family:system-ui,sans-serif">&#x1f43e; Animals RSS</a>
<a href="/feed/history.xml" style="display:inline-flex;align-items:center;gap:4px;background:#fce7f3;color:#9d174d;padding:5px 12px;border-radius:20px;font-size:12px;font-weight:600;text-decoration:none;font-family:system-ui,sans-serif">&#x1f3db; History RSS</a>
<a href="/feed/environment.xml" style="display:inline-flex;align-items:center;gap:4px;background:#dcfce7;color:#166534;padding:5px 12px;border-radius:20px;font-size:12px;font-weight:600;text-decoration:none;font-family:system-ui,sans-serif">&#x1f33f; Environment RSS</a>
<a href="/feed/technology.xml" style="display:inline-flex;align-items:center;gap:4px;background:#e0e7ff;color:#0369a1;padding:5px 12px;border-radius:20px;font-size:12px;font-weight:600;text-decoration:none;font-family:system-ui,sans-serif">&#x1f4bb; Technology RSS</a>
</div>
<p style="font-size:12px;color:#718096;margin:8px 0 0">Each category feed updates automatically with new articles in that topic area.</p>
</details>
</div>
</div>
</div>

<div class="sub-card">
<div class="icon">&#128241;</div>
<div>
<h3>Add to Home Screen <span class="sub-badge badge-free">Free · iPhone &amp; Android</span></h3>
<p>Turn KiddieDaily into a home screen app — no app store needed. Open the site in Safari or Chrome, then add it to your home screen for one-tap daily access.</p>
<div class="action">
<details style="cursor:pointer">
<summary style="font-size:13px;font-weight:600;color:#1a4d80;list-style:none">&#9654; iPhone/Safari instructions</summary>
<ol style="font-size:13px;color:#4a5568;padding-left:20px;margin:8px 0;line-height:1.7">
<li>Open <strong>kiddiedaily.com</strong> in Safari</li>
<li>Tap the <strong>Share button</strong> (box with arrow) at the bottom</li>
<li>Scroll down and tap <strong>"Add to Home Screen"</strong></li>
<li>Name it "KiddieDaily" and tap <strong>Add</strong></li>
</ol>
</details>
<details style="cursor:pointer;margin-top:6px">
<summary style="font-size:13px;font-weight:600;color:#1a4d80;list-style:none">&#9654; Android/Chrome instructions</summary>
<ol style="font-size:13px;color:#4a5568;padding-left:20px;margin:8px 0;line-height:1.7">
<li>Open <strong>kiddiedaily.com</strong> in Chrome</li>
<li>Tap the <strong>three-dot menu</strong> (top right)</li>
<li>Tap <strong>"Add to Home screen"</strong></li>
<li>Tap <strong>Add</strong></li>
</ol>
</details>
</div>
</div>
</div>

<div class="sub-card">
<div class="icon">&#128278;</div>
<div>
<h3>Bookmark the Daily Digest <span class="sub-badge badge-free">Free</span></h3>
<p>The <a href="/digest/latest.html" style="color:#1a4d80">Daily Digest</a> always shows the most recent day&#39;s articles in one clean page. Bookmark it and check it with your morning coffee.</p>
<div class="action">
<a href="/digest/latest.html" style="background:#1a4d80;color:#fff;padding:8px 16px;border-radius:6px;font-size:13px;text-decoration:none;font-family:system-ui,sans-serif">Open today&#39;s digest</a>
</div>
</div>
</div>

<div class="sub-card" style="opacity:.8">
<div class="icon">&#128140;</div>
<div>
<h3>Email Newsletter <span class="sub-badge badge-soon">Coming soon</span></h3>
<p>A morning email with the day&#39;s top 5 kid-safe stories, bias ratings, and one parent discussion question. We&#39;re building this — sign up below to be notified when it launches.</p>
<div class="action">
<p style="font-size:13px;color:#718096">Email newsletter is not yet available. Use RSS or add to home screen in the meantime — same content, delivered differently.</p>
</div>
</div>
</div>

<div style="background:#f0f4f8;border-radius:10px;padding:18px 22px;margin:24px 0 0;font-family:system-ui,sans-serif">
<div style="font-size:12px;font-weight:700;color:#4a5568;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px">What you get every morning</div>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;font-size:13px;color:#2d3748">
<div>&#9989; Up to 5 new stories</div>
<div>&#9989; Bias ratings on every article</div>
<div>&#9989; Parent discussion guides</div>
<div>&#9989; Science-first curation</div>
<div>&#9989; Kid-safety filtered</div>
<div>&#9989; Zero ads or trackers</div>
</div>
</div>

<div style="margin-top:20px;display:flex;gap:10px;flex-wrap:wrap">
<a href="/news/today.html" style="background:#1a4d80;color:#fff;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Today&#39;s stories</a>
<a href="/digest/latest.html" style="background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Daily digest</a>
<a href="/parents/" style="background:#f7fafc;color:#718096;border:1px solid #e2e8f0;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">For Parents</a>
</div>
</main>
{FOOTER}
</body></html>"""

    upload("subscribe/index.html", page, f"[scraper] Subscribe / stay-updated page — {total} articles")
    print(f"  Subscribe page: RSS, home screen, digest — {total} articles referenced")


def generate_static_info_pages(manifest, today):
    """Generate about.html, contact.html, privacy.html, terms.html — static info pages."""
    articles = manifest.get("articles", [])
    total = len(articles)
    sci_n = sum(1 for a in articles if a.get("is_science"))
    sci_pct = round(sci_n / total * 100) if total else 0

    def _page(title_tag, meta_desc, canonical, h1, body_inner):
        return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title_tag}</title>
<meta name="description" content="{meta_desc}">
<meta property="og:title" content="{title_tag}">
<meta property="og:description" content="{meta_desc}">
<meta property="og:url" content="https://kiddiedaily.com{canonical}">
<meta property="og:image" content="https://kiddiedaily.com/og-science.svg">
<meta name="twitter:card" content="summary">
<link rel="canonical" href="https://kiddiedaily.com{canonical}">
{CSS}
</head><body>
{HEADER}
<main id="main" style="max-width:720px;margin:0 auto;padding:32px 24px 64px;font-family:system-ui,sans-serif;line-height:1.65;color:#2d3748">
<h1 style="font-size:26px;margin:0 0 20px">{h1}</h1>
{body_inner}
</main>
{FOOTER}
</body></html>"""

    # ── About ──────────────────────────────────────────────────────────────────
    about_body = f"""
<p style="font-size:16px;color:#4a5568">KiddieDaily is a free, independent daily news service for families. We believe every parent deserves access to balanced, kid-safe news — without paywalls, ads, or political spin.</p>

<h2 style="font-size:18px;margin:24px 0 10px;color:#1a4d80">Our mission</h2>
<p>Ground-level news for parents: so you have the unbiased data you need to make the best decisions for your child. We don&#39;t tell you what to think — we give you the landscape, and the tools to read it critically.</p>

<h2 style="font-size:18px;margin:24px 0 10px;color:#1a4d80">How it works</h2>
<p>Every morning at 6am ET, our automated scraper collects stories from <strong>36 vetted sources</strong> spanning the full political spectrum. Each story is:</p>
<ul style="padding-left:20px;margin:8px 0">
<li>Filtered through a kid-safety blocklist (violence, explicit content, age-inappropriate topics)</li>
<li>Ranked to prioritize science, discovery, and nature over political conflict</li>
<li>Bias-rated using <strong>AllSides</strong> and <strong>Ad Fontes Media</strong> methodology</li>
<li>Grouped when multiple outlets cover the same topic — so you can compare framing</li>
</ul>
<p>We publish up to 11 new articles per day. Science-focused sources are weighted higher because they tend to be more universally relevant to families and less politically charged.</p>

<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:16px 20px;margin:20px 0">
<p style="margin:0;font-size:14px;color:#1e40af"><strong>By the numbers:</strong> {total} articles published &middot; {sci_pct}% science content &middot; 36 sources &middot; 0 ads &middot; 0 trackers &middot; updated daily at 6am ET</p>
</div>

<h2 style="font-size:18px;margin:24px 0 10px;color:#1a4d80">Our principles</h2>
<ol style="padding-left:20px;margin:8px 0">
<li><strong>Balance over narrative.</strong> We pull from Left, Center, and Right outlets. No single outlet is always right or always wrong.</li>
<li><strong>Science first.</strong> Discovery, nature, space, and health science take priority over political conflict.</li>
<li><strong>Kid-safe filtering.</strong> Our blocklist removes violence, explicit content, and age-inappropriate material before any article is considered.</li>
<li><strong>Parent-grade transparency.</strong> Every article shows which outlets covered it and how they lean. You see the bias before you read the story.</li>
<li><strong>No agenda.</strong> We&#39;re not affiliated with any political party, religion, or advocacy organization. We&#39;re a family project.</li>
</ol>

<h2 style="font-size:18px;margin:24px 0 10px;color:#1a4d80">Who runs KiddieDaily?</h2>
<p>KiddieDaily is a project of <strong>Legacy Bridge Alliance Group</strong>, a family-owned holding company building digital tools for families and kids. We also operate <a href="https://kiddiesketch.com" rel="noopener" style="color:#1a4d80">KiddieSketch</a>, <a href="https://kiddiego.com" rel="noopener" style="color:#1a4d80">KiddieGo</a>, and <a href="https://kiddiewordle.com" rel="noopener" style="color:#1a4d80">KiddieWordle</a>.</p>
<p>Have feedback? Reach us at <a href="/contact.html" style="color:#1a4d80">contact page</a>.</p>

<div style="margin-top:28px;display:flex;gap:10px;flex-wrap:wrap">
<a href="/news/today.html" style="background:#1a4d80;color:#fff;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none">Today&#39;s stories</a>
<a href="/parents/" style="background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none">For Parents</a>
<a href="/fact-check/" style="background:#f7fafc;color:#718096;border:1px solid #e2e8f0;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none">Media literacy</a>
</div>"""

    # ── Contact ────────────────────────────────────────────────────────────────
    contact_body = """
<p style="font-size:16px;color:#4a5568">Have a question, a story tip, or feedback about KiddieDaily? We&#39;d love to hear from you.</p>

<div style="background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:20px 24px;margin:20px 0;box-shadow:0 1px 4px rgba(0,0,0,.05)">
<h2 style="font-size:17px;margin:0 0 12px;color:#1a4d80">Reach us by email</h2>
<p style="margin:0 0 8px">General questions and feedback:</p>
<p style="margin:0"><a href="mailto:hello@kiddiedaily.com" style="color:#1a4d80;font-weight:600;font-size:16px">hello@kiddiedaily.com</a></p>
</div>

<div style="background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:20px 24px;margin:14px 0;box-shadow:0 1px 4px rgba(0,0,0,.05)">
<h2 style="font-size:17px;margin:0 0 12px;color:#1a4d80">Story tip or content concern?</h2>
<p style="margin:0">If you spot a story that shouldn&#39;t be on KiddieDaily (inappropriate for kids, factually wrong, or bias-rated incorrectly), please email:</p>
<p style="margin:8px 0 0"><a href="mailto:content@kiddiedaily.com" style="color:#1a4d80;font-weight:600;font-size:16px">content@kiddiedaily.com</a></p>
<p style="margin:8px 0 0;font-size:13px;color:#718096">We review all reports within 24 hours and will remove or correct the story if warranted.</p>
</div>

<div style="background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:20px 24px;margin:14px 0;box-shadow:0 1px 4px rgba(0,0,0,.05)">
<h2 style="font-size:17px;margin:0 0 12px;color:#1a4d80">Media or partnership inquiries</h2>
<p style="margin:0"><a href="mailto:partners@kiddiedaily.com" style="color:#1a4d80;font-weight:600">partners@kiddiedaily.com</a></p>
<p style="margin:8px 0 0;font-size:13px;color:#718096">We&#39;re open to partnerships with schools, libraries, and family-focused organizations that align with our mission of unbiased, kid-safe news.</p>
</div>

<p style="font-size:13px;color:#718096;margin:20px 0 0">KiddieDaily is operated by Legacy Bridge Alliance Group. We typically respond within 1–2 business days.</p>"""

    # ── Privacy ────────────────────────────────────────────────────────────────
    privacy_body = f"""
<p style="font-size:13px;color:#718096">Last updated: {today}</p>
<p style="font-size:16px;color:#4a5568">KiddieDaily is designed from the ground up with privacy in mind — especially for children. We collect the minimum possible data to operate the site.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">What we collect</h2>
<p><strong>Almost nothing.</strong> KiddieDaily is a static website served via GitHub Pages. We do not have accounts, logins, comment sections, or forms that collect personal information.</p>
<ul style="padding-left:20px;margin:8px 0">
<li><strong>No cookies.</strong> We set no tracking cookies, session cookies, or advertising cookies.</li>
<li><strong>No accounts.</strong> There is no sign-up, no login, and no stored user profiles.</li>
<li><strong>No ads.</strong> We run no advertising of any kind.</li>
<li><strong>No behavioral tracking.</strong> We do not track what articles you read, for how long, or what you click.</li>
</ul>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Analytics (if any)</h2>
<p>If we add analytics, we will use a cookieless, privacy-respecting tool (such as Cloudflare Web Analytics) that does not build user profiles, does not track individuals across sessions, and does not share data with third parties. We will update this policy before enabling any analytics.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Third-party links</h2>
<p>KiddieDaily links to external news sources (BBC, NPR, NASA, etc.) and fact-checking sites. Clicking those links takes you to third-party websites with their own privacy policies. We are not responsible for their data practices.</p>
<p>We also link to external educational resources (Snopes, AllSides, PBS NewsHour). These are informational links, not tracking partnerships.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Children&#39;s privacy (COPPA)</h2>
<p>KiddieDaily is designed to be used by families and does not knowingly collect personal information from children under 13. Because we collect no personal data at all, we believe we comply with the Children&#39;s Online Privacy Protection Act (COPPA). If you believe your child&#39;s information has been collected in error, contact us at <a href="mailto:privacy@kiddiedaily.com" style="color:#1a4d80">privacy@kiddiedaily.com</a> and we will delete it promptly.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">RSS content</h2>
<p>KiddieDaily aggregates headlines and summaries from public RSS feeds published by third-party news organizations. We link back to original articles and do not republish full copyrighted content. If you represent a news organization and have a concern about how we display your content, please contact us.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Contact</h2>
<p>Privacy questions: <a href="mailto:privacy@kiddiedaily.com" style="color:#1a4d80">privacy@kiddiedaily.com</a> &middot; <a href="/contact.html" style="color:#1a4d80">Contact page</a></p>"""

    # ── Terms ──────────────────────────────────────────────────────────────────
    terms_body = f"""
<p style="font-size:13px;color:#718096">Last updated: {today}</p>
<p style="font-size:16px;color:#4a5568">By using KiddieDaily, you agree to these terms. They&#39;re short and written in plain language.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">What KiddieDaily is</h2>
<p>KiddieDaily is a free news aggregation and curation service. We pull headlines and summaries from public RSS feeds and display them in a kid-safe, bias-labeled format for families. We are not a news organization — we do not produce original journalism.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Content accuracy</h2>
<p>We curate news to be kid-appropriate and balanced, but we do not independently verify every fact. The bias ratings we display (from AllSides and Ad Fontes Media) are methodological estimates, not legal judgments. Always read the original source and think critically.</p>
<p>KiddieDaily is provided &ldquo;as is.&rdquo; We make no warranties about the accuracy, completeness, or suitability of the content for any particular purpose.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Content ownership</h2>
<p>Article summaries and headlines remain the property of their original publishers. We display them under fair use for informational and educational purposes, with attribution and links back to the original source. KiddieDaily&#39;s own editorial text, design, and code are &copy; 2026 Legacy Bridge Alliance Group. Our commentary, page design, parent guides, and discussion prompts are our original work.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Prohibited uses</h2>
<ul style="padding-left:20px;margin:8px 0">
<li>Do not scrape or republish KiddieDaily content at scale without permission</li>
<li>Do not use KiddieDaily content to train AI models without written permission</li>
<li>Do not use our bias ratings to misrepresent news outlets as facts</li>
</ul>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Limitation of liability</h2>
<p>KiddieDaily and Legacy Bridge Alliance Group are not liable for any decisions made based on content displayed on this site. We are a news curation tool, not a professional advisor of any kind (legal, medical, financial, or otherwise).</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Changes</h2>
<p>We may update these terms. The &ldquo;last updated&rdquo; date at the top will reflect any changes. Continued use of the site after an update means you accept the new terms.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Contact</h2>
<p><a href="mailto:hello@kiddiedaily.com" style="color:#1a4d80">hello@kiddiedaily.com</a> &middot; <a href="/contact.html" style="color:#1a4d80">Contact page</a></p>"""

    upload("about.html", _page("About KiddieDaily — News for Families", "KiddieDaily is a free, ad-free daily news service for families. Learn about our mission, sources, and editorial principles.", "/about.html", "About KiddieDaily", about_body), "[scraper] Generate about.html")
    upload("contact.html", _page("Contact — KiddieDaily", "Get in touch with KiddieDaily for feedback, story tips, or partnership inquiries.", "/contact.html", "Contact Us", contact_body), "[scraper] Generate contact.html")
    upload("privacy.html", _page("Privacy Policy — KiddieDaily", "KiddieDaily privacy policy. No cookies, no accounts, no ads. Designed for families.", "/privacy.html", "Privacy Policy", privacy_body), "[scraper] Generate privacy.html")
    upload("terms.html", _page("Terms of Use — KiddieDaily", "KiddieDaily terms of use. Plain language, short version.", "/terms.html", "Terms of Use", terms_body), "[scraper] Generate terms.html")
    print(f"  Static pages: about, contact, privacy, terms — all deployed")


def generate_fact_check_page(manifest):
    """Generate /fact-check/index.html — media literacy + fact-check hub for families."""
    articles = manifest.get("articles", [])
    multi_source = [a for a in articles if a.get("n_sources", 1) > 1]
    n_multi = len(multi_source)
    total = len(articles)

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Fact Check — KiddieDaily Media Literacy Hub</title>
<meta name="description" content="Help your family spot bias, check facts, and read news critically. KiddieDaily's media literacy guide for parents and kids.">
<meta property="og:title" content="Fact Check — KiddieDaily Media Literacy Hub">
<meta property="og:description" content="Help your family spot bias, check facts, and read news critically.">
<meta property="og:url" content="https://kiddiedaily.com/fact-check/">
<meta property="og:image" content="https://kiddiedaily.com/og-science.svg">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="https://kiddiedaily.com/fact-check/">
{CSS}
<style>
.fc-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:16px 0}}
.fc-card{{background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:18px 20px;box-shadow:0 1px 4px rgba(0,0,0,.05)}}
.fc-card .icon{{font-size:28px;margin-bottom:10px}}
.fc-card h3{{margin:0 0 8px;font-size:16px;color:#1a4d80}}
.fc-card p{{margin:0;font-size:14px;color:#4a5568;line-height:1.55}}
.fc-step{{display:flex;gap:14px;align-items:flex-start;margin:12px 0;padding:14px 16px;background:#f7fafc;border-radius:8px}}
.fc-step .num{{font-size:22px;font-weight:700;color:#1a4d80;min-width:32px;line-height:1.2}}
.fc-step p{{margin:0;font-size:14px;color:#2d3748;line-height:1.55}}
.source-row{{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid #f0f0f0}}
.source-row:last-child{{border-bottom:none}}
.bias-pip{{width:12px;height:12px;border-radius:50%;flex-shrink:0}}
.tip-box{{background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:16px 20px;margin:16px 0}}
.tip-box h4{{margin:0 0 8px;font-size:14px;font-weight:700;color:#1e40af}}
.tip-box p,ul{{margin:0;font-size:14px;color:#1e3a8a;line-height:1.6}}
.tip-box ul{{padding-left:20px}}
</style>
</head><body>
{HEADER}
<main id="main" style="max-width:780px;margin:0 auto;padding:32px 24px 64px">
<h1 style="font-size:28px;margin:0 0 6px">Fact Check &amp; Media Literacy</h1>
<p style="color:#718096;font-family:system-ui,sans-serif;font-size:15px;margin:0 0 24px">
Helping families read the news with open eyes — no agenda, no spin.
</p>

<div style="background:#fff8e1;border:1px solid #fde68a;border-radius:10px;padding:16px 20px;margin:0 0 24px;font-family:system-ui,sans-serif">
<div style="font-size:11px;font-weight:700;color:#92400e;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">&#128202; KiddieDaily by the numbers</div>
<div style="display:flex;gap:24px;flex-wrap:wrap;font-size:14px;color:#92400e">
<span><strong>{total}</strong> articles analyzed</span>
<span><strong>{n_multi}</strong> covered by 2+ outlets</span>
<span><strong>11</strong> sources bias-rated</span>
<span><strong>0</strong> ads or trackers</span>
</div>
</div>

<div style="font-size:11px;font-weight:700;color:#718096;text-transform:uppercase;letter-spacing:1.2px;margin:0 0 12px">What is media bias?</div>
<div class="fc-grid">
<div class="fc-card"><div class="icon">&#129300;</div><h3>Framing bias</h3><p>The same fact can sound different depending on the words chosen. "Police responded to a protest" vs. "Police cracked down on demonstrators" — same event, different frame.</p></div>
<div class="fc-card"><div class="icon">&#128269;</div><h3>Selection bias</h3><p>News outlets choose WHAT to cover. A story that's big on Fox News might barely appear on NPR — and vice versa. Neither absence means it didn't happen.</p></div>
<div class="fc-card"><div class="icon">&#128226;</div><h3>Tone bias</h3><p>Word choice, headline intensity, and photo selection all carry emotion. Positive tone toward one group, negative toward another — that's bias at work.</p></div>
<div class="fc-card"><div class="icon">&#9878;&#65039;</div><h3>Source bias</h3><p>Who gets quoted? When one side of a story gets more expert voices than the other, the story feels more credible even if the evidence isn't.</p></div>
</div>

<div style="font-size:11px;font-weight:700;color:#718096;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 12px">How KiddieDaily measures bias</div>
<p style="font-size:15px;color:#2d3748;margin:0 0 12px;line-height:1.6">We use the same methodology as journalism schools and independent researchers: <strong>AllSides</strong> and <strong>Ad Fontes Media</strong> bias ratings. These were built by analyzing thousands of articles, surveying readers across the political spectrum, and measuring factual accuracy vs. emotional language.</p>

<div style="overflow-x:auto;margin:0 0 20px">
<table style="width:100%;border-collapse:collapse;font-family:system-ui,sans-serif;font-size:14px">
<thead><tr style="background:#f7fafc;text-align:left">
<th style="padding:10px 12px;border-bottom:2px solid #e2e8f0">Outlet</th>
<th style="padding:10px 12px;border-bottom:2px solid #e2e8f0">Bias score</th>
<th style="padding:10px 12px;border-bottom:2px solid #e2e8f0">Lean</th>
</tr></thead>
<tbody>
<tr class="source-row"><td style="padding:8px 12px">&#128251; BBC News</td><td style="padding:8px 12px">&#8722;0.3</td><td style="padding:8px 12px;color:#2b6cb0">Slight Left</td></tr>
<tr class="source-row" style="background:#fafafa"><td style="padding:8px 12px">&#128251; NPR</td><td style="padding:8px 12px">&#8722;0.7</td><td style="padding:8px 12px;color:#2b6cb0">Left-leaning</td></tr>
<tr class="source-row"><td style="padding:8px 12px">&#127757; Al Jazeera</td><td style="padding:8px 12px">&#8722;0.4</td><td style="padding:8px 12px;color:#2b6cb0">Slight Left</td></tr>
<tr class="source-row" style="background:#fafafa"><td style="padding:8px 12px">&#9878;&#65039; The Hill</td><td style="padding:8px 12px">+0.1</td><td style="padding:8px 12px;color:#276749">Center</td></tr>
<tr class="source-row"><td style="padding:8px 12px">&#129413; Fox News</td><td style="padding:8px 12px">+1.3</td><td style="padding:8px 12px;color:#c53030">Right-leaning</td></tr>
<tr class="source-row" style="background:#fafafa"><td style="padding:8px 12px">&#128640; NASA</td><td style="padding:8px 12px">0.0</td><td style="padding:8px 12px;color:#276749">Center (Science)</td></tr>
<tr class="source-row"><td style="padding:8px 12px">&#128300; Science Daily</td><td style="padding:8px 12px">0.0</td><td style="padding:8px 12px;color:#276749">Center (Science)</td></tr>
<tr class="source-row" style="background:#fafafa"><td style="padding:8px 12px">&#127963;&#65039; Smithsonian</td><td style="padding:8px 12px">&#8722;0.1</td><td style="padding:8px 12px;color:#276749">Center</td></tr>
<tr class="source-row"><td style="padding:8px 12px">&#128225; Science News</td><td style="padding:8px 12px">0.0</td><td style="padding:8px 12px;color:#276749">Center (Science)</td></tr>
<tr class="source-row" style="background:#fafafa"><td style="padding:8px 12px">&#127759; EarthSky</td><td style="padding:8px 12px">0.0</td><td style="padding:8px 12px;color:#276749">Center (Science)</td></tr>
<tr class="source-row"><td style="padding:8px 12px">&#129516; Live Science</td><td style="padding:8px 12px">0.0</td><td style="padding:8px 12px;color:#276749">Center (Science)</td></tr>
</tbody></table>
</div>

<div style="font-size:11px;font-weight:700;color:#718096;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 12px">How to fact-check any story — 5 steps</div>
<div class="fc-step"><div class="num">1</div><p><strong>Find the original claim.</strong> What exactly is being said? A headline often exaggerates. Read past the first paragraph before reacting.</p></div>
<div class="fc-step"><div class="num">2</div><p><strong>Who is the source?</strong> Is it a named expert, an anonymous source, or "studies show"? Named, on-record sources are more reliable than unnamed ones.</p></div>
<div class="fc-step"><div class="num">3</div><p><strong>Search for the same story elsewhere.</strong> Does the BBC report it the same way as Fox News? If the facts differ, someone may have gotten it wrong — or be spinning it.</p></div>
<div class="fc-step"><div class="num">4</div><p><strong>Check a fact-checking site.</strong> Google Fact Check Explorer, Snopes, and PolitiFact all search thousands of verified claims. Type any claim into their search bar.</p></div>
<div class="fc-step"><div class="num">5</div><p><strong>Ask: what is this story missing?</strong> Good reporting names who benefits, who is harmed, what happened before, and what experts disagree. Missing any of these? Keep reading.</p></div>

<div style="font-size:11px;font-weight:700;color:#718096;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 12px">Trusted fact-check tools (external)</div>
<div class="fc-grid">
<div class="fc-card"><div class="icon">&#128269;</div><h3>Google Fact Check Explorer</h3><p>Search any claim. Shows what independent fact-checkers worldwide have ruled on thousands of stories.</p><p style="margin-top:10px"><a href="https://toolbox.google.com/factcheck/explorer" rel="noopener nofollow" target="_blank" style="color:#1a4d80;font-size:13px">Open Fact Check Explorer &rarr;</a></p></div>
<div class="fc-card"><div class="icon">&#129300;</div><h3>Snopes</h3><p>The oldest fact-checking site. Strong on viral rumors, internet hoaxes, and "did that really happen" questions.</p><p style="margin-top:10px"><a href="https://www.snopes.com" rel="noopener nofollow" target="_blank" style="color:#1a4d80;font-size:13px">Visit Snopes &rarr;</a></p></div>
<div class="fc-card"><div class="icon">&#9878;&#65039;</div><h3>AllSides</h3><p>Side-by-side coverage of the same story from Left, Center, and Right outlets. Great for seeing how framing changes the narrative.</p><p style="margin-top:10px"><a href="https://www.allsides.com" rel="noopener nofollow" target="_blank" style="color:#1a4d80;font-size:13px">Visit AllSides &rarr;</a></p></div>
<div class="fc-card"><div class="icon">&#128202;</div><h3>Ad Fontes Media</h3><p>News source ratings on a chart showing both political bias AND reliability. Used by schools and newsrooms.</p><p style="margin-top:10px"><a href="https://adfontesmedia.com" rel="noopener nofollow" target="_blank" style="color:#1a4d80;font-size:13px">Visit Ad Fontes Media &rarr;</a></p></div>
</div>

<div class="tip-box">
<h4>&#128161; Family activity: spot the framing</h4>
<p>Pick any story from today&#39;s KiddieDaily. Then:</p>
<ul>
<li>Read the KiddieDaily version</li>
<li>Search the headline on Google News and find 2 other outlets covering it</li>
<li>Ask: What words did each outlet choose? What did they emphasize? What did they leave out?</li>
<li>Discuss: Is the core fact the same across all three? What&#39;s different?</li>
</ul>
<p style="margin-top:8px">This is how journalists learn to read news critically — and it works for kids as young as 9.</p>
</div>

<div style="margin-top:24px;display:flex;gap:10px;flex-wrap:wrap">
<a href="/news/today.html" style="background:#1a4d80;color:#fff;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Today&#39;s stories</a>
<a href="/parents/" style="background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">For Parents</a>
<a href="/search.html" style="background:#f7fafc;color:#718096;border:1px solid #e2e8f0;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Search all articles</a>
</div>
</main>
{FOOTER}
</body></html>"""

    upload("fact-check/index.html", page, "[scraper] Fact Check / media literacy hub page")
    print(f"  Fact-check page: {total} articles referenced, {n_multi} multi-source")


def generate_games_page(manifest):
    """Generate /games/index.html — media literacy games and educational activities for families."""
    articles = manifest.get("articles", [])
    sci_articles = [a for a in articles if a.get("is_science")]
    world_articles = [a for a in articles if not a.get("is_science")]
    # Pick 8 quiz articles: 6 recent science + 2 recent world news
    recent_sci = sci_articles[-30:] if len(sci_articles) >= 30 else sci_articles
    step = max(1, len(recent_sci) // 6)
    quiz_sci = [recent_sci[min(i * step, len(recent_sci) - 1)] for i in range(6)]
    quiz_world = world_articles[-3:] if world_articles else []
    quiz_pool = (quiz_sci + quiz_world[:2])[:8]

    stop = {"about", "their", "these", "those", "would", "could", "which", "where",
            "there", "after", "other", "first", "world", "using", "study", "finds",
            "found", "shows", "says", "that", "have", "with", "from", "this", "will",
            "into", "been", "more", "also", "than", "when", "were", "they"}

    # True/False quiz: pick 6 science articles and alternate TRUE (real fact) / FALSE (word-swapped)
    _FALSE_SWAPS = [
        ("increased", "decreased"), ("larger", "smaller"), ("faster", "slower"),
        ("older", "younger"), ("more", "fewer"), ("higher", "lower"),
        ("warmer", "cooler"), ("longer", "shorter"), ("deeper", "shallower"),
        ("new", "previously known"), ("rare", "common"), ("found", "ruled out"),
        ("growing", "shrinking"), ("expanding", "contracting"), ("ancient", "modern"),
    ]
    tf_pool_raw = [a for a in sci_articles if a.get("description") and len(a.get("description", "")) > 50]
    tf_pool_raw = tf_pool_raw[-20:] if len(tf_pool_raw) >= 20 else tf_pool_raw
    tf_items = []
    tf_idx = 0
    for a in tf_pool_raw:
        if len(tf_items) >= 6:
            break
        desc = a.get("description", "").strip()
        sentence = re.split(r"(?<=[.!?])\s", desc)[0].rstrip(".!? ")
        if len(sentence) < 35 or len(sentence) > 180:
            continue
        if tf_idx % 2 == 0:
            tf_items.append(("true", sentence, a.get("slug", "")))
        else:
            false_stmt = sentence
            swapped = False
            for tw, fw in _FALSE_SWAPS:
                if re.search(tw, false_stmt, re.IGNORECASE):
                    false_stmt = re.sub(tw, fw, false_stmt, flags=re.IGNORECASE, count=1)
                    swapped = True
                    break
            if swapped:
                tf_items.append(("false", false_stmt, a.get("slug", "")))
            else:
                tf_items.append(("true", sentence, a.get("slug", "")))
        tf_idx += 1

    tf_correct_js = "[" + ",".join(f'"{it[0]}"' for it in tf_items) + "]"
    tf_slugs_js = "[" + ",".join(f'"{it[2]}"' for it in tf_items) + "]"

    # Word Scramble game: pick 5 distinct science words (5+ letters) from recent articles
    _SCRAMBLE_STOPS = {
        "about", "their", "these", "those", "would", "could", "which", "where", "there",
        "after", "other", "first", "world", "using", "study", "finds", "found", "shows",
        "says", "that", "have", "with", "from", "this", "will", "into", "been", "more",
        "also", "than", "when", "were", "they", "some", "each", "then", "into", "here",
        "research", "scientists", "researchers", "according", "published", "discovered",
        "observed", "suggests", "reveals", "scientists", "study", "new", "old", "may",
        "humans", "human", "earth", "years", "year", "time", "times", "place", "what",
        "known", "turns", "makes", "could", "might", "should", "now", "just", "data",
        "helps", "shows", "even", "over", "under", "back", "away", "long", "high",
        "deep", "wide", "fast", "slow", "large", "small", "great", "little", "large",
    }

    def _scramble_word(word):
        """Scramble a word deterministically using quarter-rotation."""
        w = word.upper()
        n = len(w)
        if n < 4:
            return w
        q = max(1, n // 4)
        scrambled = w[q:] + w[:q]
        if scrambled == w:
            scrambled = w[0] + w[-1:0:-1]
        return scrambled

    seen_scramble = set()
    scramble_items = []
    for a in sci_articles[-60:]:
        if len(scramble_items) >= 5:
            break
        title = a.get("display_title", a.get("title", ""))
        hint = title[:50] + ("…" if len(title) > 50 else "")
        slug = a.get("slug", "")
        for w in re.sub(r"[^\w\s]", "", title).split():
            if (len(w) >= 5 and w.lower() not in _SCRAMBLE_STOPS
                    and w.isalpha() and w.lower() not in seen_scramble):
                seen_scramble.add(w.lower())
                scrambled = _scramble_word(w)
                if scrambled != w.upper():
                    scramble_items.append((w.upper(), scrambled, hint, slug))
                    break

    scramble_words_js = "[" + ",".join(f'"{it[0]}"' for it in scramble_items) + "]"
    scramble_slugs_js = "[" + ",".join(f'"{it[3]}"' for it in scramble_items) + "]"
    scramble_html = ""
    for i, (word, scrambled, hint, slug) in enumerate(scramble_items):
        scramble_html += (
            f'<div style="background:#f7fafc;border:1px solid #e2e8f0;border-radius:10px;'
            f'padding:14px 18px;margin:10px 0">'
            f'<p style="font-size:13px;color:#718096;margin:0 0 4px">Hint: <em>{hint}</em></p>'
            f'<p style="font-weight:700;font-size:22px;letter-spacing:6px;color:#1a4d80;margin:4px 0 10px;font-family:monospace">{scrambled}</p>'
            f'<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">'
            f'<input id="sc{i}" type="text" placeholder="Unscramble it…" maxlength="{len(word)}" '
            f'style="padding:8px 12px;font-size:15px;border:1px solid #cbd5e0;border-radius:6px;'
            f'font-family:monospace;width:140px;text-transform:uppercase" autocomplete="off">'
            f'<span id="sc{i}-result" style="display:none;font-size:13px;padding:4px 10px;border-radius:6px"></span>'
            f'</div>'
            f'</div>'
        )

    scramble_section = ""
    if scramble_items:
        scramble_section = f"""
<div class="game-card">
<span class="tag">Word Play</span>
<h3>&#128256; Science Word Scramble</h3>
<p>These words are scrambled — they all came from today&rsquo;s science headlines. Can you unscramble them?</p>
<div style="margin-top:14px">
{scramble_html}
</div>
<button onclick="(function(){{{{
  var words={scramble_words_js},slugs={scramble_slugs_js},score=0;
  for(var i=0;i<words.length;i++){{{{
    var inp=document.getElementById('sc'+i);
    var res=document.getElementById('sc'+i+'-result');
    var ok=inp.value.trim().toUpperCase()===words[i];
    if(ok)score++;
    res.style.display='inline-block';
    if(ok){{{{res.style.background='#d1fae5';res.style.color='#065f46';res.innerHTML='&#9989; '+words[i];}}}}
    else{{{{res.style.background='#fee2e2';res.style.color='#c53030';res.innerHTML='&#10060; '+words[i]+(slugs[i]?'&nbsp;<a href=\\"/' +slugs[i]+'\\" style=\\"color:#c53030;font-size:11px\\">read&nbsp;&rarr;</a>':'');}}}}
    inp.disabled=true;
  }}}}
  var s=document.getElementById('sc-summary');
  s.style.display='block';
  s.innerHTML=(score===words.length?'&#127881; Perfect! All '+words.length+' unscrambled!':score>=Math.ceil(words.length/2)?'&#128077; '+score+'/'+words.length+' — nice work!':'&#128218; '+score+'/'+words.length+' — keep reading science articles to grow your vocabulary!');
}}}})()" style="margin-top:14px;background:#1a4d80;color:#fff;border:none;padding:10px 22px;border-radius:6px;font-size:14px;cursor:pointer;font-family:system-ui,sans-serif">Check Answers</button>
<div id="sc-summary" style="display:none;margin-top:14px;padding:14px 18px;border-radius:8px;background:#eff6ff;color:#1e40af;font-size:15px;font-family:system-ui,sans-serif"></div>
</div>
"""
    tf_html = ""
    for i, (answer, stmt, slug) in enumerate(tf_items):
        tf_html += (
            f'<div class="tf-q" id="tf{i}" style="background:#f7fafc;border:1px solid #e2e8f0;'
            f'border-radius:10px;padding:14px 18px;margin:10px 0">'
            f'<p style="font-weight:600;font-size:14px;color:#2d3748;margin:0 0 10px">{i+1}. {stmt}</p>'
            f'<div style="display:flex;gap:10px">'
            f'<label style="cursor:pointer;font-size:13px;padding:6px 16px;border-radius:20px;'
            f'border:1px solid #1a4d80;color:#1a4d80;background:#fff">'
            f'<input type="radio" name="tf{i}" value="true" style="margin-right:6px">True</label>'
            f'<label style="cursor:pointer;font-size:13px;padding:6px 16px;border-radius:20px;'
            f'border:1px solid #c53030;color:#c53030;background:#fff">'
            f'<input type="radio" name="tf{i}" value="false" style="margin-right:6px">False</label>'
            f'</div>'
            f'<div id="tf{i}-result" style="display:none;margin-top:8px;padding:8px 12px;border-radius:6px;font-size:13px"></div>'
            f'</div>'
        )

    def _extract_kws(a):
        title = a.get("display_title", a.get("title", ""))
        return [w.capitalize() for w in re.sub(r"[^\w\s]", "", title.lower()).split()
                if len(w) > 4 and w not in stop]

    # Pre-compute keywords for all articles so distractors come from other real headlines
    all_kws = [_extract_kws(a) for a in quiz_pool]
    # Rotate correct answer C→A→B→... so it's never always option A
    _pos_cycle = [2, 0, 1]
    correct_positions = [_pos_cycle[i % 3] for i in range(len(quiz_pool))]

    def _quiz_item(a, idx, correct_pos):
        title = a.get("display_title", a.get("title", ""))
        my_kws = all_kws[idx]
        keyword = my_kws[0] if my_kws else "Science"
        correct_text = f"About {keyword}"
        # Distractors drawn from keywords in other quiz articles (never this article's keyword)
        other_kws = [all_kws[j][0] for j in range(len(all_kws)) if j != idx and all_kws[j]]
        if len(other_kws) < 2:
            other_kws += ["Ancient History", "Space Exploration", "Technology", "Animals", "Environment"]
        d1 = f"About {other_kws[idx % len(other_kws)]}"
        d2 = f"About {other_kws[(idx + max(1, len(other_kws) // 2)) % len(other_kws)]}"
        labels = ["A", "B", "C"]
        val_codes = ["a", "b", "c"]
        options = ["", "", ""]
        options[correct_pos] = correct_text
        d_slots = [i for i in range(3) if i != correct_pos]
        options[d_slots[0]] = d1
        options[d_slots[1]] = d2
        opts_html = "".join(
            f'<label style="cursor:pointer;font-size:14px;color:#2d3748">'
            f'<input type="radio" name="q{idx}" value="{val_codes[i]}" style="margin-right:8px"> '
            f'{labels[i]}) {options[i]}</label>\n'
            for i in range(3)
        )
        return (
            val_codes[correct_pos],
            f'<div class="quiz-q" id="q{idx}" style="background:#fff;border:1px solid #dde4ef;'
            f'border-radius:10px;padding:16px 20px;margin:12px 0">'
            f'<p style="font-weight:700;font-size:15px;color:#1a4d80;margin:0 0 12px">'
            f'Q{idx+1}. What is this headline about?<br>'
            f'<span style="font-style:italic;font-weight:400;color:#2d3748">&ldquo;{title[:90]}{"…" if len(title)>90 else ""}&rdquo;</span></p>'
            f'<div style="display:flex;flex-direction:column;gap:8px">'
            f'{opts_html}'
            f'</div>'
            f'<div id="q{idx}-result" style="margin-top:10px;padding:8px 12px;border-radius:6px;display:none;font-size:14px"></div>'
            f'</div>'
        )

    items = [_quiz_item(a, i, correct_positions[i]) for i, a in enumerate(quiz_pool)]
    correct_vals_js = "[" + ",".join(f'"{it[0]}"' for it in items) + "]"
    quiz_html = "\n".join(it[1] for it in items)

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Games — KiddieDaily Media Literacy Activities</title>
<meta name="description" content="Fun media literacy games and activities for kids. Spot the bias, quiz yourself on today's science news, and become a critical reader.">
<meta property="og:title" content="Games — KiddieDaily Media Literacy Activities">
<meta property="og:description" content="Fun bias-spotting games and science quizzes for kids. Free, no login.">
<meta property="og:url" content="https://kiddiedaily.com/games/">
<meta property="og:image" content="https://kiddiedaily.com/og-science.svg">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="https://kiddiedaily.com/games/">
{CSS}
<style>
.game-card{{background:#fff;border:1px solid #dde4ef;border-radius:12px;padding:20px 22px;margin:12px 0;box-shadow:0 1px 4px rgba(0,0,0,.05)}}
.game-card h3{{margin:0 0 8px;font-size:18px;color:#1a4d80}}
.game-card .tag{{font-size:11px;font-weight:700;color:#065f46;background:#d1fae5;padding:2px 8px;border-radius:20px;letter-spacing:.8px;text-transform:uppercase}}
.game-card p{{margin:8px 0 0;font-size:14px;color:#4a5568;line-height:1.55}}
.btn-play{{display:inline-block;margin-top:12px;background:#1a4d80;color:#fff;padding:8px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif}}
.btn-play:hover{{background:#1e3a6e}}
</style>
</head><body>
{HEADER}
<main id="main" style="max-width:780px;margin:0 auto;padding:32px 24px 64px">
<h1 style="font-size:28px;margin:0 0 6px">Games &amp; Activities</h1>
<p style="color:#718096;font-family:system-ui,sans-serif;font-size:15px;margin:0 0 24px">
Learn to read news like a pro — because critical thinking is a superpower.
</p>

<div class="game-card">
<span class="tag">Live Quiz</span>
<h3>&#129300; Headline Detective</h3>
<p>Can you figure out what today&#39;s science headlines are about from the title alone? Test your reading comprehension with real KiddieDaily stories.</p>
<div style="margin-top:16px">
{quiz_html if quiz_html else '<p style="color:#718096">No quiz available yet — check back after 6am ET!</p>'}
</div>
{f"""<button onclick="(function(){{
  var ans={correct_vals_js},score=0,total={len(quiz_pool)};
  for(var i=0;i<total;i++){{
    var el=document.querySelector('input[name=q'+i+']:checked');
    var res=document.getElementById('q'+i+'-result');
    res.style.display='block';
    if(el&&el.value===ans[i]){{score++;res.style.background='#d1fae5';res.style.color='#065f46';res.innerHTML='&#9989; Correct!'}}
    else{{res.style.background='#fee2e2';res.style.color='#c53030';res.innerHTML='&#10060; Not quite &#8212; read the full article to learn more!'}}
  }}
  var s=document.getElementById('quiz-summary');
  s.style.display='block';
  s.innerHTML='<strong>You got '+score+' out of '+total+'!</strong> '+(score===total?'&#127881; Perfect score!':score>=Math.ceil(total/2)?'&#128077; Good job &#8212; keep reading!':'&#128218; Keep practicing by reading KiddieDaily every day!');
}})()" style="margin-top:14px;background:#1a4d80;color:#fff;border:none;padding:10px 22px;border-radius:6px;font-size:14px;cursor:pointer;font-family:system-ui,sans-serif">
Check My Answers</button>
<div id="quiz-summary" style="display:none;margin-top:14px;padding:14px 18px;border-radius:8px;background:#eff6ff;color:#1e40af;font-size:15px;font-family:system-ui,sans-serif"></div>""" if quiz_pool else ""}
</div>

{"" if not tf_items else f"""
<div class="game-card">
<span class="tag">True or False</span>
<h3>&#10067; Science Fact Check</h3>
<p>These statements came from today&rsquo;s science articles &mdash; but some have been <em>slightly</em> changed to make them false. Can you spot the fakes?</p>
<div style="margin-top:14px">
{tf_html}
</div>
<button onclick="(function(){{{{
  var ans={tf_correct_js},slugs={tf_slugs_js},score=0,total={len(tf_items)};
  for(var i=0;i<total;i++){{{{
    var el=document.querySelector('input[name=tf'+i+']:checked');
    var res=document.getElementById('tf'+i+'-result');
    res.style.display='block';
    if(el&&el.value===ans[i]){{{{
      score++;
      res.style.background='#d1fae5';res.style.color='#065f46';
      res.innerHTML='&#9989; Correct! '+(ans[i]==='true'?'This really happened &mdash; ':'Good catch &mdash; this was altered. ')
        +(slugs[i]?'<a href=\\"/' + slugs[i] + '\\" style=\\"color:#065f46;font-weight:600\\">Read the article &rarr;</a>':'');
    }}}}else{{{{
      res.style.background='#fee2e2';res.style.color='#c53030';
      res.innerHTML='&#10060; '+(ans[i]==='true'?'Actually true! ':'Yep, this was altered. ')
        +(slugs[i]?'<a href=\\"/' + slugs[i] + '\\" style=\\"color:#c53030;font-weight:600\\">Read the original &rarr;</a>':'');
    }}}}
  }}}}
  var s=document.getElementById('tf-summary');
  s.style.display='block';
  s.innerHTML='<strong>You got '+score+' out of '+total+'!</strong> '
    +(score===total?'&#127881; Perfect science detective!':score>=Math.ceil(total/2)?'&#128077; Solid work &mdash; keep reading!':'&#128218; Tricky ones! Read more to sharpen your radar.');
}}}})()" style="margin-top:14px;background:#1a4d80;color:#fff;border:none;padding:10px 22px;border-radius:6px;font-size:14px;cursor:pointer;font-family:system-ui,sans-serif">Check My Answers</button>
<div id="tf-summary" style="display:none;margin-top:14px;padding:14px 18px;border-radius:8px;background:#eff6ff;color:#1e40af;font-size:15px;font-family:system-ui,sans-serif"></div>
</div>
"""}

{scramble_section}

<div class="game-card">
<span class="tag">Critical Thinking</span>
<h3>&#127919; Spot the Bias Challenge</h3>
<p>Every article on KiddieDaily shows where the outlet leans on the political spectrum. But can you spot bias in the headline itself — before you read the story?</p>
<p><strong>Try this:</strong> Read two headlines on the same topic from different outlets. Look for:
<ul style="font-size:14px;color:#4a5568;margin:8px 0;padding-left:20px;line-height:1.7">
<li>Emotional or charged words ("slams", "blasts", "soars", "fails")</li>
<li>Whose perspective is front and center</li>
<li>What facts are left out of the headline</li>
<li>Whether the headline matches the actual story</li>
</ul>
</p>
<a href="/news/today.html" class="btn-play">Try with today&#39;s stories &rarr;</a>
</div>

<div class="game-card">
<span class="tag">Fact Finding</span>
<h3>&#128269; Claim Buster</h3>
<p>Pick any headline. Now try to verify ONE fact in it using an external source. Use any of these:</p>
<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:10px">
<a href="https://toolbox.google.com/factcheck/explorer" rel="noopener nofollow" target="_blank" style="background:#eff6ff;color:#1e40af;border:1px solid #bfdbfe;padding:6px 14px;border-radius:6px;font-size:13px;text-decoration:none">Google Fact Check Explorer</a>
<a href="https://www.snopes.com" rel="noopener nofollow" target="_blank" style="background:#eff6ff;color:#1e40af;border:1px solid #bfdbfe;padding:6px 14px;border-radius:6px;font-size:13px;text-decoration:none">Snopes</a>
<a href="https://www.sciencenews.org" rel="noopener nofollow" target="_blank" style="background:#eff6ff;color:#1e40af;border:1px solid #bfdbfe;padding:6px 14px;border-radius:6px;font-size:13px;text-decoration:none">Science News</a>
<a href="https://www.nasa.gov" rel="noopener nofollow" target="_blank" style="background:#eff6ff;color:#1e40af;border:1px solid #bfdbfe;padding:6px 14px;border-radius:6px;font-size:13px;text-decoration:none">NASA.gov</a>
</div>
<p style="margin-top:12px;font-size:13px;color:#718096">If you can verify it in under 3 minutes — you just fact-checked a story. That&#39;s what journalists do all day.</p>
</div>

<div class="game-card">
<span class="tag">Science Skills</span>
<h3>&#128300; Science or Spin?</h3>
<p>Science stories have a different structure than political stories. In a good science story, you should be able to find:</p>
<ul style="font-size:14px;color:#4a5568;margin:8px 0;padding-left:20px;line-height:1.7">
<li>A named researcher or institution</li>
<li>Where the study was published (journal name)</li>
<li>How many subjects were studied</li>
<li>What the researchers actually measured</li>
<li>A caveat — what the study did NOT prove</li>
</ul>
<p style="font-size:14px;color:#4a5568;margin-top:8px">Pick a science article from KiddieDaily and see how many of these 5 you can find. If you can find all 5, it&#39;s a solid study. If you find fewer than 3, be skeptical.</p>
<a href="/news/science.html" class="btn-play">Browse science articles &rarr;</a>
</div>

<div style="background:#f0f4f8;border-radius:10px;padding:18px 22px;margin:24px 0;font-family:system-ui,sans-serif">
<div style="font-size:11px;font-weight:700;color:#4a5568;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">More free media literacy resources</div>
<div style="display:flex;gap:10px;flex-wrap:wrap">
<a href="https://newslit.org" rel="noopener nofollow" target="_blank" style="color:#1a4d80;font-size:13px;text-decoration:none">News Literacy Project</a>
<span style="color:#cbd5e0">·</span>
<a href="https://www.allsides.com/media-literacy" rel="noopener nofollow" target="_blank" style="color:#1a4d80;font-size:13px;text-decoration:none">AllSides Media Literacy</a>
<span style="color:#cbd5e0">·</span>
<a href="https://www.commonsense.org/education/articles/news-and-media-literacy-resources" rel="noopener nofollow" target="_blank" style="color:#1a4d80;font-size:13px;text-decoration:none">Common Sense Media</a>
<span style="color:#cbd5e0">·</span>
<a href="https://www.pbs.org/newshour/classroom" rel="noopener nofollow" target="_blank" style="color:#1a4d80;font-size:13px;text-decoration:none">PBS NewsHour Classroom</a>
</div>
</div>

<div style="margin-top:8px;display:flex;gap:10px;flex-wrap:wrap">
<a href="/news/today.html" style="background:#1a4d80;color:#fff;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Today&#39;s news</a>
<a href="/fact-check/" style="background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Fact Check guide</a>
<a href="/parents/" style="background:#f7fafc;color:#718096;border:1px solid #e2e8f0;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">For Parents</a>
</div>
</main>
{FOOTER}
</body></html>"""

    upload("games/index.html", page, "[scraper] Games / media literacy activities page")
    print(f"  Games page: {len(quiz_pool)} quiz questions ({len([a for a in quiz_pool if a.get('is_science')])} science + {len([a for a in quiz_pool if not a.get('is_science')])} world)")


def generate_draw_page(manifest, today):
    """Generate /draw/index.html — 'Draw the News' creativity studio.

    Turns real, kid-friendly headlines (space/animals/science/history/environment)
    into imagination prompts, plus an in-browser doodle pad. Bridges KiddieDaily
    news with hands-on creativity. Privacy-safe: the canvas never leaves the browser
    (no upload, no tracking) — consistent with our data-sovereignty rule.
    """
    articles = manifest.get("articles", [])
    VISUAL_CATS = {"space", "animals", "history", "environment", "science"}

    def _visual(a):
        return bool(set(a.get("cats") or []) & VISUAL_CATS) or a.get("is_science")

    pool = [a for a in articles if _visual(a)]
    recent = list(reversed(pool[-60:] if len(pool) >= 60 else pool))  # newest first

    stop = {"about", "their", "these", "those", "would", "could", "which", "where",
            "there", "after", "other", "first", "world", "using", "study", "finds",
            "found", "shows", "says", "that", "have", "with", "from", "this", "will",
            "into", "been", "more", "also", "than", "when", "were", "they", "scientists",
            "research", "researchers", "reveals", "could", "study", "new", "how", "why",
            "what", "reveal", "discover", "discovered", "suggests"}

    ICON = {"space": "🚀", "animals": "🐾", "history": "🏛️", "environment": "🌱", "science": "🔬"}
    PROMPTS = {
        "space": [
            "Draw what you think {t} looks like up close — add colors nobody has ever seen in space.",
            "Design your very own rocket ship to go explore {t}. What's inside the cockpit?",
            "Imagine you live near {t}. Draw your space house and the view out the window.",
        ],
        "animals": [
            "Draw {t} in its home. What is it doing right now?",
            "Invent a brand-new animal inspired by {t}. Give it a silly name!",
            "Draw {t} having the best day ever. What made it so good?",
        ],
        "history": [
            "Draw a scene from the time of {t}. What are people wearing?",
            "If you could time-travel to {t}, draw what you'd pack in your backpack.",
            "Draw the coolest thing you'd want to see if you visited {t}.",
        ],
        "environment": [
            "Draw our planet the way you hope it looks in 100 years.",
            "Invent a machine that could help with {t}. Draw how it works.",
            "Draw your dream treehouse that helps take care of {t}.",
        ],
        "science": [
            "Scientists just learned something new about {t}. Draw what YOU imagine it looks like.",
            "Invent a gadget that uses {t}. What does it do?",
            "Draw yourself as a scientist studying {t}. What's in your lab?",
        ],
    }

    def _topic(a):
        title = a.get("display_title", a.get("title", ""))
        words = [w for w in re.sub(r"[^\w\s]", "", title.lower()).split()
                 if len(w) > 3 and w not in stop and w.isalpha()]
        return words[0] if words else "this discovery"

    def _dom_cat(a):
        cats = set(a.get("cats") or [])
        for c in ("space", "animals", "history", "environment"):
            if c in cats:
                return c
        return "science"

    def _prompt_for(cat, topic, idx):
        lst = PROMPTS.get(cat, PROMPTS["science"])
        return lst[(idx + len(topic)) % len(lst)].replace("{t}", topic)

    # De-duplicate by topic word; take up to 6 distinct picks (newest first)
    seen, picks = set(), []
    for a in recent:
        t = _topic(a)
        if t in seen:
            continue
        seen.add(t)
        picks.append(a)
        if len(picks) >= 6:
            break

    PALETTE = [("#1a4d80", "blue"), ("#e53e3e", "red"), ("#dd6b20", "orange"),
               ("#d69e2e", "yellow"), ("#38a169", "green"), ("#805ad5", "purple"),
               ("#d53f8c", "pink"), ("#1a202c", "black")]
    swatches_html = "".join(
        f'<button class="sw{" sel" if i == 0 else ""}" data-color="{c}" '
        f'style="background:{c}" title="{n}" aria-label="{n} crayon"></button>'
        for i, (c, n) in enumerate(PALETTE)
    )

    if picks:
        feat = picks[0]
        feat_cat, feat_topic = _dom_cat(feat), _topic(feat)
        feat_prompt = _prompt_for(feat_cat, feat_topic, 0)
        feat_slug = feat.get("slug", "")
        feat_title = feat.get("display_title", feat.get("title", ""))
        feat_src = (f'Inspired by a real story: <a href="/{feat_slug}" '
                    f'style="color:#2b6cb0;text-decoration:none;font-weight:600">{feat_title} &rarr;</a>'
                    ) if feat_slug else "A fresh challenge, every day."
    else:
        feat_cat, feat_topic = "science", "a curious discovery"
        feat_prompt = "Draw the most amazing thing you can imagine a scientist discovering today."
        feat_src = "A fresh challenge, every day."

    more = picks[1:6]
    more_cards = ""
    for i, a in enumerate(more):
        cat, topic = _dom_cat(a), _topic(a)
        prompt = _prompt_for(cat, topic, i + 1)
        title = a.get("display_title", a.get("title", ""))
        slug = a.get("slug", "")
        read = (f'<a href="/{slug}">Read the story &rarr;</a>') if slug else ""
        more_cards += (
            f'<div class="draw-spark"><div class="ic">{ICON[cat]}</div>'
            f'<p class="pr">{prompt}</p>{read}'
            f'<p class="src">Inspired by: {title[:70]}</p></div>'
        )
    if not more_cards:
        more_cards = ('<div class="draw-spark"><div class="ic">🎨</div>'
                      '<p class="pr">Check back tomorrow for fresh story sparks from the day&rsquo;s news!</p></div>')

    draw_css = (
        ".draw-hero{background:linear-gradient(135deg,#1a4d80,#2b6cb0);color:#fff;border-radius:16px;"
        "padding:28px 26px;margin:0 0 24px;font-family:system-ui,sans-serif}"
        ".draw-hero h1{margin:0 0 6px;font-size:30px}"
        ".draw-hero p{margin:0;font-size:15px;color:#dbeafe;line-height:1.5}"
        ".draw-featured{background:#fff;border:1px solid #dde4ef;border-radius:14px;padding:22px 24px;"
        "margin:0 0 26px;box-shadow:0 2px 10px rgba(0,0,0,.06)}"
        ".draw-featured .kicker{font-size:11px;font-weight:700;color:#2b6cb0;text-transform:uppercase;letter-spacing:1.2px}"
        ".draw-featured .prompt{font-size:22px;font-weight:700;color:#1a2b44;line-height:1.35;margin:8px 0 4px;font-family:system-ui,sans-serif}"
        ".draw-featured .src{font-size:12px;color:#718096;margin:0 0 16px}"
        ".pad-tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 12px}"
        ".sw{width:28px;height:28px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 0 1px #cbd5e0;cursor:pointer;padding:0}"
        ".sw.sel{box-shadow:0 0 0 2px #1a4d80;transform:scale(1.12)}"
        ".tool-btn{background:#f0f4f8;border:1px solid #cbd5e0;border-radius:8px;padding:7px 14px;font-size:13px;"
        "cursor:pointer;color:#2d3748;font-family:system-ui,sans-serif}"
        ".tool-btn.sel{background:#1a4d80;color:#fff;border-color:#1a4d80}"
        "#kd-canvas{width:100%;max-width:700px;border:2px dashed #b7c6da;border-radius:12px;touch-action:none;"
        "background:#fff;display:block;cursor:crosshair}"
        ".draw-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px;margin:14px 0 26px}"
        ".draw-spark{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:16px 18px;"
        "font-family:system-ui,sans-serif;display:flex;flex-direction:column}"
        ".draw-spark .ic{font-size:26px}"
        ".draw-spark .pr{font-size:15px;font-weight:600;color:#2d3748;line-height:1.4;margin:6px 0 10px;flex:1}"
        ".draw-spark .src{font-size:11px;color:#a0aec0;margin:8px 0 0}"
        ".draw-spark a{font-size:13px;color:#2b6cb0;text-decoration:none;font-weight:600}"
        ".parent-note{background:#f0fff4;border:1px solid #9ae6b4;border-radius:12px;padding:16px 20px;"
        "margin:6px 0 0;font-family:system-ui,sans-serif}"
        ".parent-note strong{color:#22543d}"
        ".parent-note p{margin:6px 0 0;font-size:13px;color:#276749;line-height:1.55}"
        ".parent-note a{color:#276749;font-weight:600}"
    )

    canvas_js = (
        "(function(){"
        "var c=document.getElementById('kd-canvas');if(!c)return;"
        "var ctx=c.getContext('2d');"
        "function fit(){var w=Math.min(700,(c.parentNode.clientWidth||700)-2);c.width=w;c.height=340;"
        "ctx.fillStyle='#fff';ctx.fillRect(0,0,c.width,c.height);}fit();"
        "var drawing=false,color='#1a4d80',size=4,erasing=false,last=null;"
        "function pos(e){var r=c.getBoundingClientRect();var p=(e.touches&&e.touches[0])||e;"
        "return{x:(p.clientX-r.left)*(c.width/r.width),y:(p.clientY-r.top)*(c.height/r.height)};}"
        "function start(e){drawing=true;last=pos(e);if(e.cancelable)e.preventDefault();}"
        "function move(e){if(!drawing)return;var p=pos(e);ctx.strokeStyle=erasing?'#fff':color;"
        "ctx.lineWidth=erasing?size*4:size;ctx.lineCap='round';ctx.lineJoin='round';"
        "ctx.beginPath();ctx.moveTo(last.x,last.y);ctx.lineTo(p.x,p.y);ctx.stroke();last=p;"
        "if(e.cancelable)e.preventDefault();}"
        "function end(){drawing=false;}"
        "c.addEventListener('pointerdown',start);c.addEventListener('pointermove',move);"
        "window.addEventListener('pointerup',end);c.addEventListener('pointerleave',end);"
        "function selOnly(el){var q=document.querySelectorAll('[data-color],#kd-eraser');"
        "for(var i=0;i<q.length;i++)q[i].classList.remove('sel');if(el)el.classList.add('sel');}"
        "var sw=document.querySelectorAll('[data-color]');"
        "for(var i=0;i<sw.length;i++){(function(b){b.addEventListener('click',function(){"
        "color=b.getAttribute('data-color');erasing=false;selOnly(b);});})(sw[i]);}"
        "var er=document.getElementById('kd-eraser');if(er)er.addEventListener('click',function(){erasing=true;selOnly(er);});"
        "var cl=document.getElementById('kd-clear');if(cl)cl.addEventListener('click',fit);"
        "var sz=document.getElementById('kd-size');if(sz)sz.addEventListener('input',function(){size=parseInt(sz.value,10)||4;});"
        "var dl=document.getElementById('kd-download');if(dl)dl.addEventListener('click',function(){"
        "var a=document.createElement('a');a.download='my-news-drawing.png';a.href=c.toDataURL('image/png');a.click();});"
        "window.addEventListener('resize',function(){var d=c.toDataURL();var img=new Image();"
        "img.onload=function(){fit();ctx.drawImage(img,0,0,c.width,c.height);};img.src=d;});"
        "})();"
    )

    featured_html = (
        '<div class="draw-featured">'
        '<div class="kicker">&#9999;&#65039; Today&rsquo;s Drawing Challenge</div>'
        f'<p class="prompt">{feat_prompt}</p>'
        f'<p class="src">{feat_src}</p>'
        '<div class="pad-tools">'
        f'{swatches_html}'
        '<button id="kd-eraser" class="tool-btn">Eraser</button>'
        '<label class="tool-btn" style="cursor:default">Brush '
        '<input id="kd-size" type="range" min="2" max="20" value="4" style="vertical-align:middle;width:70px"></label>'
        '<button id="kd-clear" class="tool-btn">Clear</button>'
        '<button id="kd-download" class="tool-btn" style="background:#38a169;color:#fff;border-color:#38a169">&#11015; Save my drawing</button>'
        '</div>'
        '<canvas id="kd-canvas" height="340"></canvas>'
        '<p style="font-size:12px;color:#a0aec0;margin:8px 0 0">Your drawing stays on your device &mdash; nothing is uploaded. Save it to keep it! &#127912;</p>'
        '</div>'
    )

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Draw the News — KiddieDaily Creativity Studio</title>
<meta name="description" content="Turn real science, space, and animal headlines into fun drawing challenges. A free, screen-light creativity studio for kids — from KiddieDaily.">
<meta property="og:title" content="Draw the News — KiddieDaily Creativity Studio">
<meta property="og:description" content="Real headlines become drawing challenges. A free creativity studio for curious kids.">
<meta property="og:url" content="https://kiddiedaily.com/draw/">
<meta property="og:image" content="https://kiddiedaily.com/og-science.svg">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="https://kiddiedaily.com/draw/">
{CSS}
<style>{draw_css}</style>
</head><body>
{HEADER}
<main id="main" style="max-width:820px;margin:0 auto;padding:28px 24px 64px">
<div class="draw-hero">
<h1>&#127912; Draw the News</h1>
<p>Every day we turn a real science, space, or animal story into a drawing challenge. Grab crayons or use the doodle pad below — then imagine away!</p>
</div>
{featured_html}
<div style="font-size:11px;font-weight:700;color:#718096;text-transform:uppercase;letter-spacing:1.2px;margin:0 0 12px">More story sparks to draw</div>
<div class="draw-grid">
{more_cards}
</div>
<div class="parent-note">
<strong>&#127912; For grown-ups</strong>
<p>&ldquo;Draw the News&rdquo; turns real science and nature stories into imagination prompts &mdash; great for screen-light play. Print a prompt, hand over the crayons, and talk about the story together.</p>
<p>Love what your child makes? Our sister site <a href="https://kiddiesketch.com" rel="noopener">KiddieSketch</a> can turn a favorite drawing into a real keepsake.</p>
</div>
<div style="margin-top:22px;display:flex;gap:10px;flex-wrap:wrap">
<a href="/news/today.html" style="background:#1a4d80;color:#fff;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Today&#39;s news</a>
<a href="/games/" style="background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Games &amp; quizzes</a>
<a href="/news/science.html" style="background:#f7fafc;color:#718096;border:1px solid #e2e8f0;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">More science</a>
</div>
</main>
{FOOTER}
<script>{canvas_js}</script>
</body></html>"""

    upload("draw/index.html", page, "[scraper] Draw the News creativity studio")
    print(f"  Draw page: featured challenge + {len(more)} story-spark prompts")


def generate_explore_by_wonder_page(manifest, today):
    """Generate /wonder/index.html — 'Explore by Wonder' themed discovery hub.

    A browse-by-curiosity experience: instead of flat category lists, the day's
    kid-safe stories are auto-assembled into a handful of themed "wonder
    collections" (Space Week, Animal Kingdom, Time Travelers, Planet Protectors,
    Curious Minds) — each a visual card grid of recent stories in that theme.
    Borrows the discovery/collections mechanic from the KiddieGo megastore.

    Static + privacy-safe: all collection assembly happens at build time in
    Python (deterministic — identical corpora produce identical HTML). The only
    client JS is a presentational theme-chip filter that shows/hides collections
    already on the page; it fetches nothing, stores nothing, and sets no cookies
    (consistent with our data-sovereignty rule). Never surfaces world/politics.
    """
    articles = manifest.get("articles", [])

    # Ordered theme definitions. Each: key, emoji, name, tagline, gradient, tint,
    # ink, and the manifest cats that belong to it. Only visual/is_science cats
    # are ever eligible — world/politics is intentionally absent.
    THEMES = [
        ("space", "\U0001F680", "Space Week",
         "Rockets, planets, moons and everything beyond the sky.",
         "#3730a3", "#5b21b6", "#ede9fe", ("space",)),
        ("animals", "\U0001F43E", "Animal Kingdom",
         "Creatures big, small, furry, scaly and everything in between.",
         "#92400e", "#b45309", "#fef3c7", ("animals",)),
        ("history", "\U0001F3DB️", "Time Travelers",
         "Journeys into the past — long-ago people, places and discoveries.",
         "#9d174d", "#be185d", "#fce7f3", ("history",)),
        ("environment", "\U0001F30D", "Planet Protectors",
         "Our Earth, its weather, oceans and how we help keep it healthy.",
         "#166534", "#15803d", "#dcfce7", ("environment",)),
        ("science", "\U0001F52C", "Curious Minds",
         "Big questions, clever experiments and brand-new science.",
         "#1a4d80", "#2b6cb0", "#e0e7ff", ("science", "technology")),
    ]

    # Categories we will NEVER surface, regardless of anything else.
    BLOCK_CATS = {"world"}
    # Categories that make an article eligible for the wonder hub at all.
    ELIGIBLE_CATS = {"space", "animals", "history", "environment", "science", "technology"}

    date_rx = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
    MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    def _date_from_slug(slug):
        """Derive (iso, pretty) date from the slug prefix; ('', '') if none."""
        m = date_rx.search(slug or "")
        if not m:
            return "", ""
        y, mo, d = m.group(1), m.group(2), m.group(3)
        try:
            pretty = f"{MONTHS[int(mo) - 1]} {int(d)}, {y}"
        except (ValueError, IndexError):
            pretty = ""
        return f"{y}-{mo}-{d}", pretty

    def _eligible(a):
        cats = set(a.get("cats") or [])
        if cats & BLOCK_CATS:
            return False
        return bool(cats & ELIGIBLE_CATS) or bool(a.get("is_science"))

    def _esc(s):
        return (str(s or "")
                .replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    # Scan the whole corpus newest-first so every theme fills its collection from
    # its own freshest matches (a shared recent-window starves rarer cats and
    # collapsed the hub to a single "Curious Minds" collection).
    pool = [a for a in articles if _eligible(a)]
    recent = list(reversed(pool))

    def _in_theme(a, theme_cats):
        cats = set(a.get("cats") or [])
        if cats & set(theme_cats):
            return True
        # is_science stories with no explicit visual cat fall into Curious Minds.
        if "science" in theme_cats and a.get("is_science") and not (cats & ELIGIBLE_CATS):
            return True
        return False

    MAX_PER_COLLECTION = 6
    collections = []          # list of (theme_tuple, [articles])
    total_featured = 0
    for theme in THEMES:
        key, emoji, name, tagline, grad, grad2, tint, theme_cats = theme
        seen_titles = set()
        picks = []
        for a in recent:
            if not _in_theme(a, theme_cats):
                continue
            t = (a.get("display_title") or a.get("title") or "").strip().lower()
            if t and t in seen_titles:
                continue
            seen_titles.add(t)
            picks.append(a)
            if len(picks) >= MAX_PER_COLLECTION:
                break
        if picks:
            collections.append((theme, picks))
            total_featured += len(picks)

    # ── Build the theme filter chips (one per non-empty collection) ──────────
    chips_html = '<button class="wf-chip wf-chip-all is-on" data-theme="all" type="button">All wonders</button>'
    for (theme, picks) in collections:
        key, emoji, name, tagline, grad, grad2, tint, theme_cats = theme
        chips_html += (
            f'<button class="wf-chip" data-theme="{key}" type="button" '
            f'style="--wf-ink:{grad}">'
            f'<span aria-hidden="true">{emoji}</span> {_esc(name)} '
            f'<span class="wf-chip-n">{len(picks)}</span></button>'
        )

    # ── Build each collection block + its story cards ────────────────────────
    def _card(a):
        slug = a.get("slug", "")
        title = a.get("display_title") or a.get("title") or "Untitled story"
        desc = a.get("description") or ""
        if len(desc) > 118:
            desc = desc[:117].rstrip() + "…"
        iso, pretty = _date_from_slug(slug)
        n = a.get("n_sources", 1) or 1
        href = f"/{_esc(slug)}" if slug else "/news/"
        meta_bits = []
        if pretty:
            meta_bits.append(_esc(pretty))
        if n > 1:
            meta_bits.append(f"{n} outlets")
        meta = " &middot; ".join(meta_bits)
        desc_html = f'<p class="wc-ex">{_esc(desc)}</p>' if desc else ""
        meta_html = f'<div class="wc-meta">{meta}</div>' if meta else ""
        return (
            f'<a class="wc" href="{href}">'
            f'<h3 class="wc-t">{_esc(title)}</h3>'
            f'{desc_html}{meta_html}'
            f'<span class="wc-go">Read this story &rarr;</span>'
            f'</a>'
        )

    collections_html = ""
    for (theme, picks) in collections:
        key, emoji, name, tagline, grad, grad2, tint, theme_cats = theme
        cards = "".join(_card(a) for a in picks)
        collections_html += (
            f'<section class="wcoll" data-theme="{key}" '
            f'style="--wc-grad:{grad};--wc-grad2:{grad2};--wc-tint:{tint}">'
            f'<header class="wcoll-h">'
            f'<div class="wcoll-ic" aria-hidden="true">{emoji}</div>'
            f'<div><h2 class="wcoll-t">{_esc(name)}</h2>'
            f'<p class="wcoll-sub">{_esc(tagline)}</p></div>'
            f'<span class="wcoll-count">{len(picks)} '
            f'{"story" if len(picks) == 1 else "stories"}</span>'
            f'</header>'
            f'<div class="wc-grid">{cards}</div>'
            f'</section>'
        )

    n_collections = len(collections)
    if not collections_html:
        collections_html = (
            '<div class="wonder-empty">'
            '<div class="we-ic" aria-hidden="true">\U0001F52D</div>'
            '<p>Fresh wonder collections are being assembled from today&rsquo;s '
            'discoveries. Check back soon &mdash; new stories arrive every day!</p>'
            '<a class="we-btn" href="/news/">Browse all Kid News &rarr;</a>'
            '</div>'
        )

    # Stat strip values (all build-time, deterministic).
    stat_collections = n_collections
    stat_stories = total_featured
    stat_themes = len(THEMES)

    # ── Page-specific CSS as a PLAIN string (no f-string braces anywhere) ────
    page_css = (
        ".wonder-hero{background:linear-gradient(135deg,#1a4d80,#2b6cb0 60%,#5b21b6);"
        "color:#fff;border-radius:18px;padding:30px 28px;margin:0 0 22px;"
        "font-family:system-ui,sans-serif}"
        ".wonder-hero h1{margin:0 0 8px;font-size:31px;line-height:1.15}"
        ".wonder-hero p{margin:0;font-size:15px;color:#dbeafe;line-height:1.5;max-width:60ch}"
        ".wonder-stats{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0 0}"
        ".wonder-stats .st{background:rgba(255,255,255,.14);border-radius:10px;"
        "padding:8px 14px;font-size:13px;font-family:system-ui,sans-serif;color:#fff}"
        ".wonder-stats .st b{font-size:18px;display:block;line-height:1.1}"
        ".wf-bar{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 22px;"
        "font-family:system-ui,sans-serif}"
        ".wf-chip{background:#fff;border:1.5px solid #dde4ef;border-radius:22px;"
        "padding:7px 14px;font-size:13px;font-weight:600;color:#2d3748;cursor:pointer;"
        "display:inline-flex;align-items:center;gap:6px;line-height:1}"
        ".wf-chip:hover{border-color:var(--wf-ink,#1a4d80);color:var(--wf-ink,#1a4d80)}"
        ".wf-chip.is-on{background:var(--wf-ink,#1a4d80);border-color:var(--wf-ink,#1a4d80);color:#fff}"
        ".wf-chip-all{--wf-ink:#1a4d80}"
        ".wf-chip-n{background:rgba(0,0,0,.08);border-radius:20px;padding:1px 7px;"
        "font-size:11px;font-weight:700}"
        ".wf-chip.is-on .wf-chip-n{background:rgba(255,255,255,.25)}"
        ".wcoll{background:#fff;border:1px solid #e6e9f0;border-radius:16px;"
        "padding:20px 22px 22px;margin:0 0 22px;box-shadow:0 2px 10px rgba(0,0,0,.05);"
        "border-top:5px solid var(--wc-grad,#1a4d80)}"
        ".wcoll-h{display:flex;align-items:center;gap:14px;margin:0 0 16px;flex-wrap:wrap}"
        ".wcoll-ic{width:48px;height:48px;border-radius:12px;background:var(--wc-tint,#e0e7ff);"
        "display:flex;align-items:center;justify-content:center;font-size:26px;flex-shrink:0}"
        ".wcoll-t{margin:0;font-size:21px;color:var(--wc-grad,#1a4d80);"
        "font-family:system-ui,sans-serif;line-height:1.2}"
        ".wcoll-sub{margin:2px 0 0;font-size:13px;color:#718096;"
        "font-family:system-ui,sans-serif;line-height:1.4}"
        ".wcoll-count{margin-left:auto;font-size:11px;font-weight:700;letter-spacing:.6px;"
        "text-transform:uppercase;color:var(--wc-grad2,#2b6cb0);background:var(--wc-tint,#e0e7ff);"
        "padding:4px 10px;border-radius:20px;white-space:nowrap}"
        ".wc-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}"
        ".wc{display:flex;flex-direction:column;background:#fbfcfe;border:1px solid #e8ecf3;"
        "border-radius:12px;padding:14px 16px;text-decoration:none;color:inherit;"
        "font-family:system-ui,sans-serif;transition:border-color .12s,box-shadow .12s,transform .12s}"
        ".wc:hover{border-color:var(--wc-grad,#1a4d80);box-shadow:0 4px 14px rgba(0,0,0,.09);"
        "transform:translateY(-2px);text-decoration:none}"
        ".wc-t{margin:0 0 6px;font-size:15px;font-weight:700;color:#1a2b44;line-height:1.32}"
        ".wc-ex{margin:0 0 10px;font-size:12.5px;color:#4a5568;line-height:1.45;flex:1}"
        ".wc-meta{font-size:11px;color:#94a3b8;margin:0 0 10px}"
        ".wc-go{font-size:12px;font-weight:700;color:var(--wc-grad2,#2b6cb0);margin-top:auto}"
        ".wonder-empty{background:#fff;border:1px dashed #cbd5e0;border-radius:16px;"
        "padding:34px 26px;text-align:center;font-family:system-ui,sans-serif;color:#4a5568}"
        ".wonder-empty .we-ic{font-size:38px;margin-bottom:10px}"
        ".wonder-empty p{margin:0 auto 16px;max-width:44ch;font-size:15px;line-height:1.55}"
        ".we-btn,.wonder-cta a{display:inline-block;background:#1a4d80;color:#fff;"
        "padding:9px 18px;border-radius:8px;font-size:14px;text-decoration:none}"
        ".wonder-note{background:#f0f9ff;border:1px solid #bae6fd;border-radius:14px;"
        "padding:16px 20px;margin:8px 0 22px;font-family:system-ui,sans-serif}"
        ".wonder-note strong{color:#075985}"
        ".wonder-note p{margin:6px 0 0;font-size:13px;color:#0c4a6e;line-height:1.55}"
        ".wonder-cta{margin-top:8px;display:flex;gap:10px;flex-wrap:wrap;"
        "font-family:system-ui,sans-serif}"
        ".wonder-cta a.alt{background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80}"
        ".wonder-cta a.ghost{background:#f7fafc;color:#718096;border:1px solid #e2e8f0}"
        "@media(max-width:640px){.wonder-hero{padding:24px 20px}.wonder-hero h1{font-size:26px}"
        ".wcoll{padding:16px 16px 18px}.wcoll-count{margin-left:0}}"
        "@media(prefers-color-scheme:dark){"
        ".wf-chip{background:#1a202c;border-color:#2d3748;color:#e2e8f0}"
        ".wcoll{background:#161b26;border-color:#2d3748}"
        ".wc{background:#1a202c;border-color:#2d3748}"
        ".wc-t{color:#e2e8f0}.wc-ex{color:#a0aec0}.wc-meta{color:#718096}"
        ".wonder-note{background:#0c2536;border-color:#1e3a52}.wonder-note p{color:#bae6fd}"
        ".wonder-empty{background:#161b26;border-color:#2d3748;color:#a0aec0}}"
        "@media(prefers-reduced-motion:reduce){.wc{transition:none}.wc:hover{transform:none}}"
    )

    # ── Client JS as a PLAIN string: presentational filter only (no data) ────
    filter_js = (
        "(function(){"
        "var chips=document.querySelectorAll('.wf-chip');"
        "var colls=document.querySelectorAll('.wcoll');"
        "if(!chips.length||!colls.length)return;"
        "function apply(theme){"
        "for(var i=0;i<colls.length;i++){"
        "var show=(theme==='all'||colls[i].getAttribute('data-theme')===theme);"
        "colls[i].style.display=show?'':'none';}"
        "for(var j=0;j<chips.length;j++){"
        "chips[j].classList.toggle('is-on',chips[j].getAttribute('data-theme')===theme);}"
        "}"
        "for(var k=0;k<chips.length;k++){(function(btn){"
        "btn.addEventListener('click',function(){apply(btn.getAttribute('data-theme'));"
        "var m=document.getElementById('wonder-collections');"
        "if(m&&window.scrollTo){var y=m.getBoundingClientRect().top+window.pageYOffset-70;"
        "window.scrollTo({top:y<0?0:y,behavior:'smooth'});}});"
        "})(chips[k]);}"
        "})();"
    )

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Explore by Wonder — KiddieDaily Discovery Collections</title>
<meta name="description" content="Browse the day's kid-safe news by curiosity: themed wonder collections like Space Week, Animal Kingdom, Time Travelers and Planet Protectors — a discovery hub from KiddieDaily.">
<meta property="og:title" content="Explore by Wonder — KiddieDaily Discovery Collections">
<meta property="og:description" content="Themed collections of real, kid-safe news stories. Follow your curiosity through space, animals, history, the planet and more.">
<meta property="og:url" content="https://kiddiedaily.com/wonder/">
<meta property="og:image" content="https://kiddiedaily.com/og-science.svg">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="https://kiddiedaily.com/wonder/">
{CSS}
<style>{page_css}</style>
</head><body>
{HEADER}
<main id="main" style="max-width:820px;margin:0 auto;padding:28px 24px 64px">
<div class="wonder-hero">
<h1>&#128302; Explore by Wonder</h1>
<p>Don&rsquo;t just scroll the headlines &mdash; follow your curiosity. We&rsquo;ve gathered the day&rsquo;s kid-safe stories into themed <strong>wonder collections</strong> so you can dive into whatever amazes you most.</p>
<div class="wonder-stats">
<div class="st"><b>{stat_collections}</b>collections today</div>
<div class="st"><b>{stat_stories}</b>stories to explore</div>
<div class="st"><b>{stat_themes}</b>wonder themes</div>
</div>
</div>
<div class="wf-bar" role="group" aria-label="Filter wonder collections by theme">
{chips_html}
</div>
<div id="wonder-collections">
{collections_html}
</div>
<div class="wonder-note">
<strong>&#128302; For grown-ups</strong>
<p>&ldquo;Explore by Wonder&rdquo; is a browse-by-curiosity view of the same bias-rated, kid-safe stories on KiddieDaily &mdash; grouped by theme instead of a flat list. Tap a theme chip to focus on one wonder, or explore them all. Every story links to our full write-up with sources.</p>
</div>
<div class="wonder-cta">
<a href="/news/today.html">Today&#39;s news</a>
<a class="alt" href="/news/">All Kid News</a>
<a class="ghost" href="/games/">Games &amp; quizzes</a>
</div>
</main>
{FOOTER}
<script>{filter_js}</script>
</body></html>"""

    upload("wonder/index.html", page, "[scraper] Explore by Wonder discovery collections hub")
    print(f"  Wonder hub: {n_collections} collections, {total_featured} stories featured")


def generate_maya_hello(manifest, today):
    """Generate /hello/index.html — "Maya's Daily Hello", a warm avatar front door.

    Maya is a friendly inline-SVG guide (borrowed from the GoGoMaya kid avatar)
    who greets kids and gives a short, kid-voiced take on the single most
    wonder-sparking science story of the day, plus one open "I wonder..."
    question and a link to read more. Deterministic pick + template phrasing —
    NO live LLM, nothing uploaded, no cookies/trackers (data-sovereignty safe).
    An emotional, among-friends entry point to the news for ages 8-12.
    """
    articles = manifest.get("articles", [])
    VISUAL_CATS = {"space", "animals", "history", "environment", "science"}

    def _esc(s):
        return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    def _wonder(a):
        # Prefer real science / visual-nature stories; never surface world/politics.
        return bool(set(a.get("cats") or []) & VISUAL_CATS) or a.get("is_science")

    # Newest-first pool of kid-safe, wonder-sparking stories (use the TAIL for recent).
    pool = [a for a in articles if _wonder(a)]
    recent = list(reversed(pool[-40:] if len(pool) >= 40 else pool))

    STOP = {"about", "their", "these", "those", "would", "could", "which", "where",
            "there", "after", "other", "first", "world", "using", "study", "finds",
            "found", "shows", "says", "that", "have", "with", "from", "this", "will",
            "into", "been", "more", "also", "than", "when", "were", "they", "your",
            "scientists", "research", "researchers", "reveals", "reveal", "discover",
            "discovered", "suggests", "according", "amazing", "here", "just", "like",
            # leading superlatives/fillers so the topic word lands on a real noun
            "oldest", "newest", "largest", "smallest", "biggest", "giant", "tiny",
            "hidden", "secret", "rare", "brand", "super", "mega", "incredible",
            "surprising", "mysterious", "ever", "seen", "photo", "picture", "video",
            "over", "under", "near", "deep", "high", "wild", "very"}

    ICON = {"space": "\U0001F680", "animals": "\U0001F43E", "history": "\U0001F3DB️",
            "environment": "\U0001F331", "science": "\U0001F52C"}

    # Warmth-scored ranking so Maya greets the *most wonder-sparking* story, not
    # merely the newest. Deterministic: depends only on corpus content, not clock.
    WONDER_WORDS = ("discover", "new", "first", "found", "mystery", "hidden", "secret",
                    "giant", "tiny", "space", "star", "planet", "moon", "galaxy",
                    "dinosaur", "fossil", "ancient", "ocean", "deep", "glow", "rare",
                    "oldest", "largest", "smallest", "baby", "rescue", "surprise",
                    "volcano", "comet", "meteor", "whale", "shark", "octopus")
    CAT_WEIGHT = {"space": 5, "animals": 5, "environment": 3, "history": 3, "science": 2}

    def _dom_cat(a):
        cats = set(a.get("cats") or [])
        for c in ("space", "animals", "history", "environment"):
            if c in cats:
                return c
        return "science"

    def _topic(a):
        title = a.get("display_title", a.get("title", ""))
        words = [w for w in re.sub(r"[^\w\s]", "", title.lower()).split()
                 if len(w) > 3 and w not in STOP and w.isalpha()]
        return words[0] if words else "this discovery"

    def _score(a, idx):
        title = (a.get("display_title", a.get("title", "")) or "").lower()
        s = CAT_WEIGHT.get(_dom_cat(a), 2)
        s += sum(2 for w in WONDER_WORDS if w in title)
        s += 2 if a.get("is_science") else 0
        s += min(int(a.get("n_sources", 1) or 1), 3)          # corroboration bonus, capped
        # Gentle recency nudge (small, deterministic — index within newest-first list).
        s += max(0, 6 - idx) * 0.1
        return s

    ranked = sorted(
        ((a, i) for i, a in enumerate(recent)),
        # Highest score wins; ties break on newer (lower idx), then title for stability.
        key=lambda p: (-_score(p[0], p[1]), p[1],
                       (p[0].get("display_title", p[0].get("title", "")) or "")),
    )
    ranked_articles = [a for a, _ in ranked]

    hero = ranked_articles[0] if ranked_articles else None

    # ── Kid-voiced template phrasing (deterministic pick by topic/cat, no random) ──
    OPENERS = [
        "Ooh, wait till you hear this one!",
        "I have got the coolest thing to tell you today.",
        "Okay, this story made my brain do a happy little flip.",
        "Guess what scientists just figured out?",
        "I found a story today that I could not stop thinking about.",
        "You are going to love this — I promise.",
    ]
    # Per-category 2nd/3rd sentences. Each uses {t} = topic word, filled safely.
    TAKES = {
        "space": [
            "Way, way out in space, {t} is doing something nobody expected. Space is basically the biggest mystery box ever, and today we get to peek inside.",
            "Somewhere out among the stars, {t} just surprised the smartest sky-watchers on Earth. Imagine how tiny and how HUGE that makes us feel at the same time.",
        ],
        "animals": [
            "A real-life animal — {t} — is doing something so clever that even scientists went 'whoa!' Animals are full of secret talents we are only just noticing.",
            "Turns out {t} has a hidden trick up its... well, it does not have sleeves, but you get the idea! Nature keeps inventing things we never would have guessed.",
        ],
        "history": [
            "People who lived a LONG time ago left behind a clue about {t}, and we just found it. It is like the past mailed us a secret letter across thousands of years.",
            "A piece of history about {t} popped back into the world today. Every old thing we dig up is a tiny time-machine for our imaginations.",
        ],
        "environment": [
            "Our amazing planet is showing us something new about {t}. Earth is the only home we have got, so every discovery about it is a big deal.",
            "Scientists learned something fresh about {t} and how our world works. The more we understand it, the better we can take care of it together.",
        ],
        "science": [
            "Curious minds just uncovered something new about {t}, and it is the kind of thing that makes you say 'but HOW?' That question is where all the best science begins.",
            "Someone in a lab followed their curiosity about {t} — and found an answer nobody had before. That is the superpower of asking good questions.",
        ],
    }
    WONDERS = {
        "space": [
            "I wonder what it would feel like to float right next to {t} and look back at Earth.",
            "I wonder what other secrets are hiding out there that we have not spotted yet.",
        ],
        "animals": [
            "I wonder what {t} would say if it could tell us about its day.",
            "I wonder how many more animal superpowers are still waiting to be discovered.",
        ],
        "history": [
            "I wonder what a kid just like you was doing back when {t} was around.",
            "I wonder what people 1,000 years from now will dig up about US.",
        ],
        "environment": [
            "I wonder what one small thing you and I could do to help {t}.",
            "I wonder what our planet will look like when you are all grown up.",
        ],
        "science": [
            "I wonder what question you would ask a scientist about {t}.",
            "I wonder what you would discover if you got to run the experiment yourself.",
        ],
    }
    SIGNOFFS = [
        "Stay curious — Maya",
        "Keep wondering — Maya",
        "See you tomorrow — Maya",
        "Your friend in wonder, Maya",
    ]

    def _pick(lst, seed):
        return lst[seed % len(lst)] if lst else ""

    if hero is not None:
        cat = _dom_cat(hero)
        topic = _topic(hero)
        seed = len(topic) + len(recent)          # deterministic, content-driven
        opener = _pick(OPENERS, seed)
        take = _pick(TAKES.get(cat, TAKES["science"]), seed).replace("{t}", topic)
        wonder = _pick(WONDERS.get(cat, WONDERS["science"]), seed + 1).replace("{t}", topic)
        signoff = _pick(SIGNOFFS, seed)
        hero_title = hero.get("display_title", hero.get("title", ""))
        hero_slug = hero.get("slug", "")
        hero_icon = ICON.get(cat, "\U0001F52C")
        read_more = (
            f'<a class="mh-read" href="/{_esc(hero_slug)}">'
            f'Read the whole story with a grown-up &nbsp;&rarr;</a>'
        ) if hero_slug else ""
    else:
        cat, topic = "science", "a curious discovery"
        opener = "Hi friend! The news is a little quiet today, but wonder never sleeps."
        take = ("I do not have a brand-new story for you this minute, so here is a "
                "tiny challenge instead: look out a window and find ONE thing you "
                "cannot fully explain. That is a mystery worth chasing.")
        wonder = "I wonder what the most curious question in the whole world is."
        signoff = "Stay curious — Maya"
        hero_title = ""
        hero_slug = ""
        hero_icon = "✨"
        read_more = ('<a class="mh-read" href="/news/today.html">'
                     'See today&rsquo;s stories &nbsp;&rarr;</a>')

    # ── A few more friendly picks Maya "also loved" (deterministic, de-duped) ──
    seen_topics = {topic}
    also = []
    for a in ranked_articles[1:]:
        t = _topic(a)
        if t in seen_topics:
            continue
        seen_topics.add(t)
        also.append(a)
        if len(also) >= 3:
            break

    also_cards = ""
    for i, a in enumerate(also):
        c = _dom_cat(a)
        t = a.get("display_title", a.get("title", ""))
        slug = a.get("slug", "")
        ic = ICON.get(c, "\U0001F52C")
        title_html = _esc(t[:88])
        inner = (
            f'<span class="mh-alt-ic" aria-hidden="true">{ic}</span>'
            f'<span class="mh-alt-t">{title_html}</span>'
        )
        if slug:
            also_cards += f'<a class="mh-alt" href="/{_esc(slug)}">{inner}</a>'
        else:
            also_cards += f'<div class="mh-alt">{inner}</div>'
    if not also_cards:
        also_cards = ('<div class="mh-alt"><span class="mh-alt-ic" aria-hidden="true">\U0001F308</span>'
                      '<span class="mh-alt-t">More wonder lands here tomorrow — check back!</span></div>')

    # ── Inline SVG avatar: Maya. Friendly star-explorer with a waving arm and
    #    twinkling stars (gentle CSS animation, disabled under reduced-motion).
    #    Kept as a plain string; no external assets. ─────────────────────────
    maya_svg = (
        '<svg class="mh-maya" viewBox="0 0 200 210" role="img" '
        'aria-label="Maya, a friendly cartoon guide, waving hello" '
        'xmlns="http://www.w3.org/2000/svg">'
        '<defs>'
        '<radialGradient id="mhSky" cx="50%" cy="38%" r="70%">'
        '<stop offset="0%" stop-color="#dbeafe"/><stop offset="100%" stop-color="#bfdbfe"/>'
        '</radialGradient>'
        '<linearGradient id="mhHair" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0%" stop-color="#3a2a5d"/><stop offset="100%" stop-color="#241a3d"/>'
        '</linearGradient>'
        '</defs>'
        '<circle cx="100" cy="100" r="96" fill="url(#mhSky)"/>'
        '<g class="mh-tw" fill="#fbbf24">'
        '<path d="M40 46 l3 7 7 3 -7 3 -3 7 -3-7 -7-3 7-3z"/>'
        '<path d="M164 60 l2.4 5.6 5.6 2.4 -5.6 2.4 -2.4 5.6 -2.4-5.6 -5.6-2.4 5.6-2.4z"/>'
        '<path d="M150 150 l2 4.6 4.6 2 -4.6 2 -2 4.6 -2-4.6 -4.6-2 4.6-2z"/>'
        '</g>'
        '<path d="M56 210 v-24 a44 44 0 0 1 88 0 v24 z" fill="#2b6cb0"/>'
        '<path d="M100 176 l4 9 9 1 -7 6 2 9 -8-5 -8 5 2-9 -7-6 9-1z" fill="#fbbf24"/>'
        '<g class="mh-wave">'
        '<path d="M138 168 q22 -10 28 -30" stroke="#f4c9a6" stroke-width="13" '
        'fill="none" stroke-linecap="round"/>'
        '<circle cx="168" cy="134" r="9" fill="#f4c9a6"/>'
        '</g>'
        '<path d="M62 168 q-16 -6 -20 -22" stroke="#f4c9a6" stroke-width="13" '
        'fill="none" stroke-linecap="round"/>'
        '<rect x="92" y="120" width="16" height="16" rx="6" fill="#f4c9a6"/>'
        '<circle cx="100" cy="98" r="34" fill="#f6d2b0"/>'
        '<path d="M64 100 a36 36 0 0 1 72 0 q-8 -14 -20 -12 q-4 -10 -16 -10 '
        'q-12 0 -16 10 q-12 -2 -20 12z" fill="url(#mhHair)"/>'
        '<circle cx="66" cy="104" r="9" fill="url(#mhHair)"/>'
        '<circle cx="134" cy="104" r="9" fill="url(#mhHair)"/>'
        '<circle cx="88" cy="98" r="4.6" fill="#2d2440"/>'
        '<circle cx="112" cy="98" r="4.6" fill="#2d2440"/>'
        '<circle cx="89.5" cy="96.5" r="1.5" fill="#fff"/>'
        '<circle cx="113.5" cy="96.5" r="1.5" fill="#fff"/>'
        '<circle cx="80" cy="108" r="5" fill="#f6a5a5" opacity=".65"/>'
        '<circle cx="120" cy="108" r="5" fill="#f6a5a5" opacity=".65"/>'
        '<path d="M88 110 q12 12 24 0" stroke="#b3573f" stroke-width="3.5" '
        'fill="none" stroke-linecap="round"/>'
        '</svg>'
    )

    # ── Page-specific CSS as a PLAIN string (interpolated as {page_css}) ──
    page_css = (
        ".mh-wrap{font-family:system-ui,-apple-system,'Segoe UI',sans-serif}"
        ".mh-hero{display:flex;gap:22px;align-items:center;flex-wrap:wrap;"
        "background:linear-gradient(135deg,#1a4d80,#2b6cb0);color:#fff;"
        "border-radius:20px;padding:24px 26px;margin:0 0 22px}"
        ".mh-maya{width:150px;height:auto;flex:0 0 auto;filter:drop-shadow(0 6px 14px rgba(0,0,0,.25))}"
        ".mh-hi{flex:1;min-width:220px}"
        ".mh-hi .mh-greet{font-size:13px;font-weight:700;letter-spacing:1.4px;"
        "text-transform:uppercase;color:#cfe4ff;margin:0 0 4px}"
        ".mh-hi h1{margin:0 0 8px;font-size:30px;line-height:1.15}"
        ".mh-hi p{margin:0;font-size:15px;color:#e3efff;line-height:1.55}"
        ".mh-bubble{position:relative;background:#fff;border:1px solid #d9e2ef;"
        "border-radius:18px;padding:22px 24px 20px;margin:0 0 20px;"
        "box-shadow:0 4px 16px rgba(20,60,110,.10)}"
        ".mh-bubble::before{content:'';position:absolute;top:-14px;left:44px;"
        "width:26px;height:26px;background:#fff;border-left:1px solid #d9e2ef;"
        "border-top:1px solid #d9e2ef;transform:rotate(45deg)}"
        ".mh-cat{display:inline-flex;align-items:center;gap:6px;font-size:12px;"
        "font-weight:700;color:#2b6cb0;text-transform:uppercase;letter-spacing:1px;margin:0 0 8px}"
        ".mh-say{font-size:19px;line-height:1.5;color:#1f2b44;margin:0 0 4px;font-weight:500}"
        ".mh-say .mh-lead{font-weight:800;color:#1a4d80}"
        ".mh-storytitle{font-size:13px;color:#6b7a90;font-style:italic;margin:10px 0 14px}"
        ".mh-wonder{background:#fff8e1;border:1px dashed #f0c15a;border-radius:14px;"
        "padding:14px 18px;margin:14px 0 16px}"
        ".mh-wonder .mh-wq-label{font-size:11px;font-weight:800;letter-spacing:1.2px;"
        "text-transform:uppercase;color:#a06a00;margin:0 0 4px}"
        ".mh-wonder p{margin:0;font-size:17px;color:#7a4e00;line-height:1.5;font-weight:600}"
        ".mh-read{display:inline-block;background:#1a4d80;color:#fff;text-decoration:none;"
        "padding:10px 18px;border-radius:9px;font-size:14px;font-weight:600}"
        ".mh-read:hover{background:#14406b;text-decoration:none}"
        ".mh-sign{text-align:right;font-size:14px;color:#2b6cb0;font-weight:700;"
        "font-style:italic;margin:16px 0 0}"
        ".mh-alt-h{font-size:11px;font-weight:800;color:#718096;text-transform:uppercase;"
        "letter-spacing:1.2px;margin:0 0 10px}"
        ".mh-alt-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));"
        "gap:12px;margin:0 0 24px}"
        ".mh-alt{display:flex;align-items:center;gap:10px;background:#fff;border:1px solid #e2e8f0;"
        "border-radius:12px;padding:12px 14px;text-decoration:none;color:#1f2b44;transition:transform .1s}"
        "a.mh-alt:hover{transform:translateY(-2px);border-color:#bcd3ef;text-decoration:none}"
        ".mh-alt-ic{font-size:22px;flex:0 0 auto}"
        ".mh-alt-t{font-size:14px;line-height:1.35;font-weight:600}"
        ".mh-grownup{background:#f0fff4;border:1px solid #9ae6b4;border-radius:14px;"
        "padding:16px 20px;margin:8px 0 0}"
        ".mh-grownup strong{color:#22543d}"
        ".mh-grownup p{margin:6px 0 0;font-size:13px;color:#276749;line-height:1.55}"
        ".mh-grownup a{color:#276749;font-weight:600}"
        ".mh-nav{margin:22px 0 0;display:flex;gap:10px;flex-wrap:wrap}"
        ".mh-nav a{padding:9px 18px;border-radius:8px;font-size:14px;text-decoration:none;"
        "font-family:system-ui,sans-serif}"
        ".mh-nav .p1{background:#1a4d80;color:#fff}"
        ".mh-nav .p2{background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80}"
        ".mh-nav .p3{background:#f7fafc;color:#718096;border:1px solid #e2e8f0}"
        "@keyframes mhWave{0%,100%{transform:rotate(0)}50%{transform:rotate(-16deg)}}"
        "@keyframes mhTw{0%,100%{opacity:.35}50%{opacity:1}}"
        ".mh-wave{transform-origin:150px 160px;animation:mhWave 1.6s ease-in-out infinite}"
        ".mh-tw{animation:mhTw 2.4s ease-in-out infinite}"
        "@media(max-width:560px){.mh-hero{padding:20px}.mh-maya{width:112px}.mh-hi h1{font-size:24px}"
        ".mh-say{font-size:17px}}"
        "@media(prefers-reduced-motion:reduce){.mh-wave,.mh-tw{animation:none}}"
        "@media(prefers-color-scheme:dark){"
        ".mh-bubble{background:#141c2b;border-color:#2a3550}"
        ".mh-bubble::before{background:#141c2b;border-color:#2a3550}"
        ".mh-say{color:#e6edf7}.mh-say .mh-lead{color:#90cdf4}.mh-storytitle{color:#9fb0c7}"
        ".mh-alt{background:#141c2b;border-color:#2a3550;color:#e6edf7}"
        ".mh-wonder{background:#2a2410;border-color:#5c4a1e}.mh-wonder p{color:#f4d58a}"
        ".mh-wonder .mh-wq-label{color:#e0b455}"
        ".mh-grownup{background:#10261a;border-color:#2f5c40}.mh-grownup p{color:#9ae6b4}"
        ".mh-grownup a{color:#9ae6b4}}"
    )

    # ── Cosmetic scroll progress-bar JS as a PLAIN string (interpolated as {js}).
    #    No data collection, no storage — purely a visual bar. ──
    js = (
        "(function(){"
        "var b=document.getElementById('kd-prog');if(!b)return;"
        "function u(){var h=document.documentElement;"
        "var m=(h.scrollHeight-h.clientHeight)||1;"
        "b.style.width=((h.scrollTop||document.body.scrollTop)/m*100)+'%';}"
        "document.addEventListener('scroll',u,{passive:true});u();"
        "})();"
    )

    # ── Non-f HTML fragments carrying dynamic (pre-escaped) text ──
    greet_line = "Maya says hi"
    bubble_cat = f'<div class="mh-cat">{hero_icon} A wonder worth sharing</div>'
    story_title_html = (
        f'<div class="mh-storytitle">&mdash; from the real story: &ldquo;{_esc(hero_title[:110])}&rdquo;</div>'
        if hero_title else ""
    )
    say_html = (
        f'<p class="mh-say"><span class="mh-lead">{_esc(opener)}</span> {_esc(take)}</p>'
    )
    wonder_html = (
        '<div class="mh-wonder"><div class="mh-wq-label">&#10024; Maya wonders&hellip;</div>'
        f'<p>{_esc(wonder)}</p></div>'
    )
    sign_html = f'<p class="mh-sign">{_esc(signoff)}</p>'

    # ── Final page. The f-string carries NO literal { } braces: every CSS/JS
    #    block is interpolated via {page_css} / {js}; dynamic text via named vars. ─
    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Maya&#39;s Daily Hello — KiddieDaily</title>
<meta name="description" content="Meet Maya, KiddieDaily&#39;s friendly guide. Every day she shares a warm, kid-voiced hello about the most wonder-sparking science story — plus an 'I wonder...' question to spark curiosity.">
<meta property="og:title" content="Maya's Daily Hello — KiddieDaily">
<meta property="og:description" content="A friendly avatar guide who greets kids with the day's most wonder-sparking science story and an 'I wonder...' question.">
<meta property="og:url" content="https://kiddiedaily.com/hello/">
<meta property="og:image" content="https://kiddiedaily.com/og-science.svg">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="https://kiddiedaily.com/hello/">
{CSS}
<style>{page_css}</style>
</head><body>
{HEADER}
<div id="kd-prog"></div>
<main id="main" style="max-width:820px;margin:0 auto;padding:28px 24px 64px">
<div class="mh-wrap">
<div class="mh-hero">
{maya_svg}
<div class="mh-hi">
<div class="mh-greet">{greet_line}</div>
<h1>Hi, I&rsquo;m Maya! &#128075;</h1>
<p>I read the news so we can be curious together. Here&rsquo;s the one story today that gave me the biggest case of the wonders.</p>
</div>
</div>
<div class="mh-bubble">
{bubble_cat}
{say_html}
{story_title_html}
{wonder_html}
{read_more}
{sign_html}
</div>
<div class="mh-alt-h">A few more things I loved today</div>
<div class="mh-alt-grid">
{also_cards}
</div>
<div class="mh-grownup">
<strong>&#128075; For grown-ups</strong>
<p>Maya is a friendly front door to the news &mdash; a warm, kid-voiced hello that turns the day&rsquo;s most wonder-sparking science story into a shared moment of curiosity. Her take and her &ldquo;I wonder&hellip;&rdquo; question are written from the real, bias-rated story linked above; nothing your child types is ever collected, and there are no trackers or ads.</p>
<p>Read the full story together, then ask your child Maya&rsquo;s wonder question and see where it leads.</p>
</div>
<div class="mh-nav">
<a class="p1" href="/news/today.html">Today&#39;s news</a>
<a class="p2" href="/draw/">Draw the news</a>
<a class="p3" href="/games/">Games &amp; quizzes</a>
</div>
</div>
</main>
{FOOTER}
<script>{js}</script>
</body></html>"""

    upload("hello/index.html", page, "[scraper] Maya's Daily Hello avatar greeter")
    print(f"  Maya's Hello: greeted with '{topic}' ({cat}) + {len(also)} extra picks")


def generate_numbers_page(manifest, today):
    """Generate /news-numbers/index.html — 'News by the Numbers' data-literacy studio.

    Data-literacy reps for kids: pull a concrete NUMBER that appears in a recent,
    kid-friendly headline/description (via a safe regex), and present it as a
    'guess the number' reveal card plus a plain-language, kid-scale sense of how
    big that figure really is (number sense). Borrows the core mechanic from
    brokerage / data-literacy practice — estimate first, then check against the
    real figure and reason about scale.

    Distinct from every other page: no multiple-choice quiz, no drawing canvas,
    no fact-check checklist — the whole page trains one skill, feeling the size
    of a number.

    Degrades gracefully: if no clean number is found in the recent corpus it
    falls back to a fixed set of evergreen, kid-safe number facts so the page
    is never empty.

    Privacy-safe & static: everything runs client-side, nothing is uploaded, no
    cookies/trackers, no external model APIs (data-sovereignty rule). Content is
    chosen deterministically (by index/length, never random or time-of-day) so an
    identical corpus produces identical output and commits stay quiet.
    """
    articles = manifest.get("articles", [])
    VISUAL_CATS = {"space", "animals", "history", "environment", "science"}

    def _kid_safe(a):
        # Prefer science / visual categories; never surface world/politics.
        cats = set(a.get("cats") or [])
        if "world" in cats:
            return False
        return bool(cats & VISUAL_CATS) or a.get("is_science")

    def _date_from_slug(slug):
        m = re.search(r"\d{4}-\d{2}-\d{2}", slug or "")
        return m.group() if m else ""

    # Recent = TAIL of the oldest->newest list, newest first (matches draw page).
    pool = [a for a in articles if _kid_safe(a)]
    recent = list(reversed(pool[-70:] if len(pool) >= 70 else pool))

    # ── safe number extraction ────────────────────────────────────────────────
    # Only plain, kid-friendly magnitudes: an optional word-multiplier
    # (thousand/million/billion/trillion) OR a short comma-grouped integer.
    # Deliberately conservative — skip decimals-as-versions, bare years, %, $,
    # ranges, and times so we never surface a garbled or scary figure.
    WORD_MULT = {
        "thousand": 1000,
        "thousands": 1000,
        "million": 1000000,
        "millions": 1000000,
        "billion": 1000000000,
        "billions": 1000000000,
        "trillion": 1000000000000,
        "trillions": 1000000000000,
    }
    # e.g. "1.5 million", "12 thousand", "3 billion"
    RE_WORD = re.compile(
        r"\b(\d{1,3}(?:\.\d{1,2})?)\s+(thousand|thousands|million|millions|billion|billions|trillion|trillions)\b",
        re.IGNORECASE,
    )
    # e.g. "1,200" / "45,000" / "300" — 1 to 4 groups, no decimals.
    RE_PLAIN = re.compile(r"(?<![\d.,$%])(\d{1,3}(?:,\d{3}){0,3})(?![\d.,%])")

    # Units we are happy to keep next to a number (kid-friendly, non-scary).
    GOOD_UNIT = re.compile(
        r"^(years?|year-old|days?|hours?|minutes?|seconds?|"
        r"miles?|kilometers?|kilometres?|km|meters?|metres?|feet|foot|pounds?|kg|kilograms?|"
        r"tons?|tonnes?|degrees?|light-?years?|species|planets?|moons?|stars?|galaxies|"
        r"eggs?|babies|chicks|penguins?|animals?|bones?|teeth|legs?|steps?|times)\b",
        re.IGNORECASE,
    )
    # Reject a match if any of these scary/adult tokens sit right next to it.
    BAD_NEAR = re.compile(
        r"\b(kill(?:ed|s|ing)?|dead|death|deaths|died|die|wound(?:ed|s)?|injur\w*|victim\w*|"
        r"war|troop\w*|weapon\w*|gun\w*|missile\w*|bomb\w*|shoot\w*|attack\w*|refugee\w*|"
        r"virus|covid|disease|cancer|tumou?r|drug\w*|arrest\w*|prison\w*|crime\w*|police|"
        r"protest\w*|riot\w*|dollars?|usd|percent|bce?)\b",
        re.IGNORECASE,
    )

    def _clean_text(s):
        return re.sub(r"\s+", " ", (s or "")).strip()

    def _kid_scale(value):
        """Return a plain-language, kid-scale comparison for an integer value."""
        v = abs(int(round(value)))
        if v <= 0:
            return "That is zero — none at all!"
        if v <= 5:
            return "You can count that on one hand."
        if v <= 12:
            return "About the number of eggs in a carton."
        if v <= 30:
            return "Roughly the number of kids in a school class."
        if v <= 100:
            return "About how many steps you take crossing a big playground."
        if v <= 1000:
            return "You'd have to count out loud for about 15 minutes to reach it."
        if v <= 10000:
            return "More than all the students in a large elementary school."
        if v <= 100000:
            return "About how many people fit in a really big sports stadium."
        if v <= 1000000:
            return "Picture every seat in ten huge stadiums, all full."
        if v <= 1000000000:
            return "That's like counting every second for over 30 years without stopping!"
        if v <= 1000000000000:
            return "More stars than you could ever count with your eyes in a whole lifetime."
        return "So huge it's hard for anyone — even grown-ups — to truly picture!"

    def _hint(value):
        """A gentle 'how many digits' hint that never leaks the exact number."""
        digits = len(str(abs(int(round(value)))))
        names = {1: "one digit", 2: "two digits", 3: "three digits", 4: "four digits"}
        if digits in names:
            return "This number has " + names[digits] + "."
        if digits <= 6:
            return "This number is in the thousands."
        if digits <= 9:
            return "This number is in the millions."
        if digits <= 12:
            return "This number is in the billions."
        return "This number is truly gigantic."

    def _fmt(value):
        return "{:,}".format(int(round(value)))

    def _extract_number(a):
        """Try to find ONE clean, kid-safe number in a title/description.

        Returns dict(value, phrase, context) or None.
        """
        title = _clean_text(a.get("display_title") or a.get("title") or "")
        desc = _clean_text(a.get("description") or "")
        for source in (title, desc):
            if not source:
                continue
            # 1) word-multiplier form first (e.g. "2 million")
            m = RE_WORD.search(source)
            if m:
                lo = max(0, m.start() - 40)
                hi = min(len(source), m.end() + 40)
                if not BAD_NEAR.search(source[lo:hi]):
                    num = float(m.group(1))
                    value = num * WORD_MULT[m.group(2).lower()]
                    if 10 <= value <= 10000000000000:
                        return {"value": value, "phrase": m.group(0), "context": source}
            # 2) plain comma-grouped integer (e.g. "45,000" or "300 eggs")
            for pm in RE_PLAIN.finditer(source):
                raw = pm.group(1)
                digits_only = raw.replace(",", "")
                if not digits_only.isdigit():
                    continue
                value = int(digits_only)
                # Skip trivially tiny, likely-year (bare 1000-2100), or huge.
                if value < 8 or value > 999999999:
                    continue
                if "," not in raw and 1000 <= value <= 2100:
                    continue  # looks like a year
                lo = max(0, pm.start() - 40)
                hi = min(len(source), pm.end() + 40)
                if BAD_NEAR.search(source[lo:hi]):
                    continue
                # Only keep if a friendly unit follows (keeps it concrete & safe).
                after = source[pm.end():pm.end() + 30].lstrip()
                if not GOOD_UNIT.match(after):
                    continue
                return {"value": value, "phrase": raw, "context": source}
        return None

    # ── evergreen fallbacks (always kid-safe, never scary) ────────────────────
    EVERGREEN = [
        {"value": 8, "label": "planets in our Solar System",
         "blurb": "Since Pluto became a 'dwarf planet' in 2006, we count eight main planets orbiting the Sun."},
        {"value": 206, "label": "bones in a grown-up human body",
         "blurb": "Babies are born with about 300 bones — some fuse together as you grow!"},
        {"value": 100, "label": "years a giant tortoise can live",
         "blurb": "Some giant tortoises have lived past 150 years — older than your great-great-grandparents!"},
        {"value": 390, "label": "kilometers per hour a peregrine falcon can dive",
         "blurb": "That makes the peregrine falcon the fastest animal on the whole planet."},
        {"value": 60000, "label": "miles of blood vessels inside your body",
         "blurb": "Lined up end to end, they could wrap around the whole Earth more than twice!"},
        {"value": 300000, "label": "kilometers per second that light travels",
         "blurb": "Nothing we know of moves faster. Sunlight takes about 8 minutes to reach us."},
    ]

    def _pick_evergreen(i):
        e = EVERGREEN[i % len(EVERGREEN)]
        return {
            "value": e["value"],
            "phrase": _fmt(e["value"]),
            "label": e["label"],
            "blurb": e["blurb"],
            "slug": "",
            "title": "",
            "date": "",
        }

    # ── build the deck (deterministic, de-duplicated by value) ────────────────
    picks, seen_vals = [], set()
    for a in recent:
        found = _extract_number(a)
        if not found:
            continue
        vkey = int(round(found["value"]))
        if vkey in seen_vals:
            continue
        seen_vals.add(vkey)
        picks.append({
            "value": found["value"],
            "phrase": found["phrase"],
            "label": "",
            "blurb": "",
            "slug": a.get("slug", ""),
            "title": a.get("display_title") or a.get("title") or "",
            "date": _date_from_slug(a.get("slug", "")),
        })
        if len(picks) >= 6:
            break

    used_fallback = False
    if len(picks) < 3:
        # Top up (or fully populate) with evergreen facts so we always have >=3.
        used_fallback = True
        i = 0
        while len(picks) < 3 and i < len(EVERGREEN):
            ev = _pick_evergreen(i)
            if int(round(ev["value"])) not in seen_vals:
                seen_vals.add(int(round(ev["value"])))
                picks.append(ev)
            i += 1

    import html as _html

    def esc(s):
        return _html.escape(s or "", quote=True)

    # ── render one card ────────────────────────────────────────────────────────
    def _card(idx, p):
        value = p["value"]
        answer = _fmt(value)
        hint = _hint(value)
        scale = _kid_scale(value)
        from_real = bool(p.get("slug"))
        if from_real:
            title = p["title"]
            source_line = (
                'From a real KiddieDaily story: '
                '<a href="/' + esc(p["slug"]) + '">' + esc(title[:80]) + ' &rarr;</a>'
            )
            date = p.get("date") or ""
            date_html = ('<span class="nb-date">' + esc(date) + '</span>') if date else ""
            question = "How big is the number hiding in this headline?"
            # Blank out the digits in the headline so kids guess before the reveal.
            masked = title
            if p.get("phrase"):
                masked = title.replace(p["phrase"], "?????", 1)
            teaser = '<p class="nb-teaser">&ldquo;' + esc(masked[:110]) + '&rdquo;</p>'
        else:
            source_line = "An evergreen number fact to warm up your number sense."
            date_html = ""
            question = "Can you guess: " + esc(p.get("label") or "what this number counts") + "?"
            teaser = ""

        extra = ('<p class="nb-extra">' + esc(p["blurb"]) + '</p>') if p.get("blurb") else ""
        reveal_extra = '<p class="nb-extra">' + esc(scale) + '</p>' + extra

        # data-answer holds the formatted number; revealed only on click via JS.
        return (
            '<div class="nb-card" data-answer="' + esc(answer) + '">'
            '<div class="nb-kicker">Number ' + str(idx + 1) + date_html + '</div>'
            '<p class="nb-q">' + question + '</p>'
            + teaser +
            '<div class="nb-guess">'
            '<label class="nb-lbl" for="nb-in-' + str(idx) + '">Your guess</label>'
            '<input class="nb-input" id="nb-in-' + str(idx) + '" type="text" inputmode="numeric" '
            'autocomplete="off" placeholder="type a number">'
            '<button class="nb-btn nb-check" type="button">Check</button>'
            '<button class="nb-btn nb-reveal" type="button">Reveal</button>'
            '</div>'
            '<p class="nb-hint">&#128161; Hint: ' + esc(hint) + '</p>'
            '<div class="nb-answer" hidden>'
            '<div class="nb-big">' + esc(answer) + '</div>'
            + reveal_extra +
            '<p class="nb-feedback" aria-live="polite"></p>'
            '<p class="nb-src">' + source_line + '</p>'
            '</div>'
            '</div>'
        )

    cards_html = "".join(_card(i, p) for i, p in enumerate(picks))

    feat = picks[0]
    feat_answer = _fmt(feat["value"])
    feat_scale = _kid_scale(feat["value"])

    fallback_note = ""
    if used_fallback:
        fallback_note = (
            '<p class="nb-note">Not many clean numbers in today&rsquo;s kid-safe stories, '
            'so we mixed in some all-time favorite number facts. Check back tomorrow for fresh ones!</p>'
        )

    n_real = sum(1 for p in picks if p.get("slug"))

    # ── page-specific CSS (PLAIN string; no f-string braces anywhere) ─────────
    page_css = (
        ".nb-hero{background:linear-gradient(135deg,#1a4d80,#2b6cb0);color:#fff;border-radius:16px;"
        "padding:28px 26px;margin:0 0 22px;font-family:system-ui,sans-serif}"
        ".nb-hero h1{margin:0 0 6px;font-size:30px}"
        ".nb-hero p{margin:0;font-size:15px;color:#dbeafe;line-height:1.5}"
        ".nb-feat{background:#f7fafc;border:1px solid #dde4ef;border-radius:14px;padding:20px 22px;"
        "margin:0 0 22px;font-family:system-ui,sans-serif}"
        ".nb-feat .k{font-size:11px;font-weight:700;color:#2b6cb0;text-transform:uppercase;letter-spacing:1.2px}"
        ".nb-feat .big{font-size:40px;font-weight:800;color:#1a4d80;line-height:1.1;margin:6px 0 2px}"
        ".nb-feat .sc{font-size:15px;color:#2d3748;line-height:1.5;margin:0}"
        ".nb-how{background:#eff6ff;border:1px solid #bfdbfe;border-radius:12px;padding:16px 20px;"
        "margin:0 0 22px;font-family:system-ui,sans-serif}"
        ".nb-how h2{margin:0 0 8px;font-size:15px;color:#1e40af;border:none;padding:0}"
        ".nb-how ol{margin:0;padding-left:20px;color:#1e3a8a;font-size:14px;line-height:1.6}"
        ".nb-note{background:#fff8e1;border:1px solid #fde68a;border-radius:10px;padding:12px 16px;"
        "margin:0 0 20px;font-size:13px;color:#92400e;font-family:system-ui,sans-serif}"
        ".nb-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;margin:0 0 26px}"
        ".nb-card{background:#fff;border:1px solid #dde4ef;border-radius:14px;padding:18px 20px;"
        "box-shadow:0 2px 8px rgba(0,0,0,.05);font-family:system-ui,sans-serif;display:flex;flex-direction:column}"
        ".nb-kicker{font-size:11px;font-weight:700;color:#2b6cb0;text-transform:uppercase;letter-spacing:1.2px;"
        "display:flex;align-items:center;gap:8px}"
        ".nb-date{font-size:10px;font-weight:600;color:#a0aec0;letter-spacing:.5px}"
        ".nb-q{font-size:17px;font-weight:700;color:#1a2b44;line-height:1.35;margin:8px 0 6px}"
        ".nb-teaser{font-size:13px;color:#4a5568;font-style:italic;margin:0 0 10px;line-height:1.45}"
        ".nb-guess{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:2px 0 10px}"
        ".nb-lbl{font-size:12px;color:#718096;width:100%;margin:0}"
        ".nb-input{flex:1;min-width:120px;font-size:16px;padding:9px 12px;border:2px solid #cbd5e0;"
        "border-radius:8px;font-family:system-ui,sans-serif;color:#1a1a1a;background:#fff}"
        ".nb-input:focus{outline:none;border-color:#1a4d80}"
        ".nb-btn{border:none;border-radius:8px;padding:9px 14px;font-size:13px;font-weight:700;cursor:pointer;"
        "font-family:system-ui,sans-serif}"
        ".nb-check{background:#1a4d80;color:#fff}"
        ".nb-reveal{background:#f0f4f8;color:#2d3748;border:1px solid #cbd5e0}"
        ".nb-hint{font-size:12px;color:#718096;margin:0 0 4px}"
        ".nb-answer{margin-top:8px;padding-top:12px;border-top:1px dashed #cbd5e0}"
        ".nb-big{font-size:30px;font-weight:800;color:#1a4d80;line-height:1.1;letter-spacing:.5px}"
        ".nb-extra{font-size:14px;color:#2d3748;line-height:1.5;margin:6px 0 0}"
        ".nb-feedback{font-size:13px;font-weight:700;margin:8px 0 0;min-height:18px}"
        ".nb-feedback.ok{color:#276749}.nb-feedback.close{color:#b7791f}.nb-feedback.off{color:#c53030}"
        ".nb-src{font-size:12px;color:#718096;margin:10px 0 0}"
        ".nb-src a{color:#2b6cb0;text-decoration:none;font-weight:600}"
        ".parent-note{background:#f0fff4;border:1px solid #9ae6b4;border-radius:12px;padding:16px 20px;"
        "margin:6px 0 0;font-family:system-ui,sans-serif}"
        ".parent-note strong{color:#22543d}"
        ".parent-note p{margin:6px 0 0;font-size:13px;color:#276749;line-height:1.55}"
        "@media(prefers-color-scheme:dark){"
        ".nb-how{background:#12233b;border-color:#1e3a5f}.nb-how h2,.nb-how ol{color:#bcd3f0}"
        ".nb-card,.nb-feat{background:#1a202c;border-color:#2d3748}"
        ".nb-q{color:#e2e8f0}.nb-teaser,.nb-extra,.nb-feat .sc{color:#cbd5e0}"
        ".nb-input{background:#0f1117;color:#e2e8f0;border-color:#4a5568}"
        ".nb-reveal{background:#2d3748;color:#e2e8f0;border-color:#4a5568}"
        ".nb-big,.nb-feat .big{color:#90cdf4}"
        ".nb-note{background:#3b2f12;border-color:#5f4a1e;color:#f0d98c}}"
    )

    # ── client JS (PLAIN string; guess-check + reveal, all client-side) ───────
    js = (
        "(function(){"
        "function digits(s){return (s||'').replace(/[^0-9]/g,'');}"
        "var cards=document.querySelectorAll('.nb-card');"
        "for(var i=0;i<cards.length;i++){(function(card){"
        "var ans=card.getAttribute('data-answer')||'';"
        "var ansNum=parseInt(digits(ans),10);"
        "var box=card.querySelector('.nb-answer');"
        "var fb=card.querySelector('.nb-feedback');"
        "var input=card.querySelector('.nb-input');"
        "var checkBtn=card.querySelector('.nb-check');"
        "var revealBtn=card.querySelector('.nb-reveal');"
        "function show(){if(box)box.hidden=false;}"
        "function feedback(){"
        "if(!fb)return;var g=parseInt(digits(input&&input.value),10);"
        "if(isNaN(g)||isNaN(ansNum)){fb.textContent='Type a number, then Reveal to see the answer!';fb.className='nb-feedback';return;}"
        "var diff=Math.abs(g-ansNum);"
        "if(diff===0){fb.textContent='\\uD83C\\uDF89 Spot on! You nailed it.';fb.className='nb-feedback ok';return;}"
        "var ratio=ansNum===0?diff:diff/Math.abs(ansNum);"
        "if(ratio<=0.1){fb.textContent='So close! You were almost exactly right.';fb.className='nb-feedback close';}"
        "else if(ratio<=0.5){fb.textContent=(g<ansNum?'A bit low — ':'A bit high — ')+'good try, you are in the right ballpark!';fb.className='nb-feedback close';}"
        "else{fb.textContent=(g<ansNum?'Lower than the real number. ':'Higher than the real number. ')+'Numbers can be surprising!';fb.className='nb-feedback off';}"
        "}"
        "if(checkBtn)checkBtn.addEventListener('click',function(){show();feedback();});"
        "if(revealBtn)revealBtn.addEventListener('click',function(){show();feedback();});"
        "if(input)input.addEventListener('keydown',function(e){if(e.key==='Enter'){show();feedback();}});"
        "})(cards[i]);}"
        "})();"
    )

    # ── page shell (f-string kept 100% free of literal { } braces) ────────────
    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>News by the Numbers — KiddieDaily Data Literacy</title>
<meta name="description" content="Guess the number hiding in a real headline, then discover how big it truly is. A free data-literacy game that builds number sense for curious kids — from KiddieDaily.">
<meta property="og:title" content="News by the Numbers — KiddieDaily Data Literacy">
<meta property="og:description" content="Guess the number in a real news headline, then feel how big it really is. Number sense for kids.">
<meta property="og:url" content="https://kiddiedaily.com/news-numbers/">
<meta property="og:image" content="https://kiddiedaily.com/og-science.svg">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="https://kiddiedaily.com/news-numbers/">
{CSS}
<style>{page_css}</style>
</head><body>
{HEADER}
<main id="main" style="max-width:820px;margin:0 auto;padding:28px 24px 64px">
<div class="nb-hero">
<h1>&#128290; News by the Numbers</h1>
<p>Every big story has a number in it. Guess how big it is first &mdash; then find out how much that number really means. This is how you build number sense!</p>
</div>
<div class="nb-feat">
<div class="k">&#127919; Warm-up number</div>
<div class="big">{feat_answer}</div>
<p class="sc">{feat_scale}</p>
</div>
<div class="nb-how">
<h2>How to play</h2>
<ol>
<li>Read the headline &mdash; the number is hidden with question marks.</li>
<li>Type your best <strong>guess</strong>. Nobody expects it to be exact!</li>
<li>Hit <strong>Reveal</strong> to see the real number and how close you were.</li>
<li>Read the &ldquo;how big is it really?&rdquo; clue to feel the size of the number.</li>
</ol>
</div>
{fallback_note}
<div class="nb-grid">
{cards_html}
</div>
<div class="parent-note">
<strong>&#128202; For grown-ups</strong>
<p>&ldquo;News by the Numbers&rdquo; turns real headlines into estimation practice &mdash; the same skill grown-ups use to sanity-check prices, distances, and data. Estimating first, then checking, is one of the strongest ways to build lasting number sense.</p>
<p>Everything runs in your browser. Nothing your child types is uploaded, saved, or tracked.</p>
</div>
<div style="margin-top:22px;display:flex;gap:10px;flex-wrap:wrap">
<a href="/news/today.html" style="background:#1a4d80;color:#fff;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Today&#39;s news</a>
<a href="/games/" style="background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Games &amp; quizzes</a>
<a href="/fact-check/" style="background:#f7fafc;color:#718096;border:1px solid #e2e8f0;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Fact Check</a>
</div>
</main>
{FOOTER}
<script>{js}</script>
</body></html>"""

    upload("news-numbers/index.html", page, "[scraper] News by the Numbers data-literacy page")
    print(f"  News-by-Numbers page: {len(picks)} number cards ({n_real} from real headlines, fallback={used_fallback})")


def generate_news_word_page(manifest, today):
    """Generate /news-word/index.html — 'News Word', a daily Wordle-style guessing game.

    The secret word is a real science/nature term (5-6 letters) pulled from a recent,
    kid-safe headline. Players type guesses and get green/yellow/gray letter feedback,
    exactly like a word-guess game; solving reveals the source article so kids can go
    read the real story behind the word.

    Distinct from the Games page word-scramble (which only unscrambles a shown word):
    this hides the word and gives per-letter hot/cold feedback across multiple guesses.

    Privacy-safe & kid-appropriate: 100% client-side, nothing uploaded, no cookies or
    trackers, no external APIs (data-sovereignty rule). The secret word is drawn only
    from science / space / animals / history / environment stories, never world/politics.

    Deterministic: the daily word is chosen by a stable hash of `today` over a sorted,
    de-duplicated candidate pool, so an identical corpus + date always yields identical
    HTML (no noisy commits between runs on the same day).
    """
    articles = manifest.get("articles", [])
    VISUAL_CATS = {"space", "animals", "history", "environment", "science"}

    def _kid_safe(a):
        # Prefer science / visual categories; never surface world/politics headlines.
        cats = set(a.get("cats") or [])
        if "world" in cats:
            return False
        return bool(cats & VISUAL_CATS) or a.get("is_science")

    # Words we never want to be the secret answer (too generic / meta / not a "term").
    STOP = {
        "about", "their", "these", "those", "would", "could", "which", "where",
        "there", "after", "other", "first", "world", "using", "study", "finds",
        "found", "shows", "says", "that", "have", "with", "from", "this", "will",
        "into", "been", "more", "also", "than", "when", "were", "they", "some",
        "each", "then", "here", "research", "reveals", "reveal", "before", "could",
        "might", "should", "known", "turns", "makes", "helps", "even", "over",
        "under", "back", "away", "long", "high", "deep", "wide", "fast", "slow",
        "large", "small", "great", "little", "years", "year", "times", "time",
        "human", "humans", "people", "north", "south", "east", "west", "still",
        "every", "again", "while", "being", "since", "among", "around", "really",
        "today", "week", "month", "learn", "learns", "learned", "amazing", "close",
        "watch", "meet", "meets", "story", "stories", "thing", "things", "kids",
    }

    # Build a candidate pool of distinct 5-6 letter alphabetic words tied to a story.
    # Walk newest->oldest so we favor recent headlines when trimming.
    recent = list(reversed(articles[-80:] if len(articles) >= 80 else articles))
    cand_map = {}  # WORD(upper) -> (slug, display_title) of the first (most recent) story
    for a in recent:
        if not _kid_safe(a):
            continue
        title = a.get("display_title", a.get("title", "")) or ""
        slug = a.get("slug", "")
        for raw in re.sub(r"[^\w\s]", " ", title).split():
            w = raw.upper()
            if (len(w) in (5, 6) and w.isalpha() and w.lower() not in STOP
                    and w not in cand_map):
                cand_map[w] = (slug, title)

    # Deterministic daily pick: sort the pool for a stable order, then index by a
    # simple hash of the date. Same corpus + same day => same word, every run.
    pool = sorted(cand_map.keys())
    if pool:
        date_key = re.sub(r"[^0-9]", "", str(today)) or "0"
        h = 0
        for ch in date_key:
            h = (h * 31 + ord(ch)) & 0x7FFFFFFF
        idx = h % len(pool)
        secret = pool[idx]
        src_slug, src_title = cand_map[secret]
    else:
        # Fallback so the page still renders on an empty/edge corpus.
        secret = "COMET"
        src_slug, src_title = "", ""

    wl = len(secret)
    max_guesses = 6

    # A tiny curated valid-guess list so kids' plausible words are accepted even if
    # they're not the secret. Filtered to the current word length; secret guaranteed in.
    COMMON_WORDS = [
        "APPLE", "BEACH", "BRAIN", "BREAD", "CHAIR", "CLOUD", "DREAM", "EARTH",
        "FIELD", "FLAME", "FRUIT", "GHOST", "GRASS", "GREEN", "HEART", "HORSE",
        "HOUSE", "JUICE", "LIGHT", "MONEY", "MUSIC", "NIGHT", "OCEAN", "PAINT",
        "PLANT", "PLATE", "RIVER", "ROBOT", "SMILE", "SNAKE", "SOUND", "SPACE",
        "STONE", "STORM", "SUGAR", "TIGER", "TRAIN", "WATER", "WHALE", "WORLD",
        "ANIMAL", "BRIDGE", "CASTLE", "DESERT", "DRAGON", "FLOWER", "FOREST",
        "FRIEND", "GARDEN", "ISLAND", "JUNGLE", "MAMMAL", "MARKET", "MONKEY",
        "PLANET", "PUZZLE", "ROCKET", "SCHOOL", "SPIDER", "SPRING", "SUMMER",
        "WINTER", "WONDER",
    ]
    valid = sorted({w for w in COMMON_WORDS if len(w) == wl} | {secret})

    # ---- JSON payloads passed to the client (all safe: a word + one slug) --------
    secret_js = json.dumps(secret)
    valid_js = json.dumps(valid)
    slug_js = json.dumps(src_slug)
    title_js = json.dumps(src_title[:90])
    wl_js = json.dumps(wl)
    max_js = json.dumps(max_guesses)

    # Human hint for the header (category emoji + short prompt), no answer leaked.
    hint_label = "science" if not src_slug else "today's science headlines"

    # ---- page-specific CSS (PLAIN string; contains all the braces) --------------
    page_css = (
        ".nw-hero{background:linear-gradient(135deg,#1a4d80,#2b6cb0);color:#fff;border-radius:16px;"
        "padding:26px 24px;margin:0 0 22px;font-family:system-ui,sans-serif}"
        ".nw-hero h1{margin:0 0 6px;font-size:30px}"
        ".nw-hero p{margin:0;font-size:15px;color:#dbeafe;line-height:1.5}"
        ".nw-board{display:grid;gap:8px;justify-content:center;margin:10px 0 6px}"
        ".nw-row{display:grid;gap:8px}"
        ".nw-tile{width:52px;height:52px;display:flex;align-items:center;justify-content:center;"
        "font-family:system-ui,sans-serif;font-size:28px;font-weight:800;text-transform:uppercase;"
        "border:2px solid #cbd5e0;border-radius:8px;color:#1a2b44;background:#fff;transition:transform .12s}"
        ".nw-tile.filled{border-color:#94a3b8}"
        ".nw-tile.pop{transform:scale(1.08)}"
        ".nw-tile.correct{background:#38a169;border-color:#38a169;color:#fff}"
        ".nw-tile.present{background:#d69e2e;border-color:#d69e2e;color:#fff}"
        ".nw-tile.absent{background:#94a3b8;border-color:#94a3b8;color:#fff}"
        ".nw-msg{min-height:24px;text-align:center;font-family:system-ui,sans-serif;font-size:15px;"
        "font-weight:600;color:#2b6cb0;margin:4px 0 10px}"
        ".nw-kb{max-width:520px;margin:8px auto 0;display:flex;flex-direction:column;gap:7px}"
        ".nw-kbrow{display:flex;justify-content:center;gap:6px}"
        ".nw-key{flex:1;min-width:0;max-width:44px;height:52px;border:none;border-radius:7px;background:#e2e8f0;"
        "color:#1a2b44;font-family:system-ui,sans-serif;font-size:15px;font-weight:700;cursor:pointer;"
        "text-transform:uppercase;padding:0}"
        ".nw-key.wide{max-width:74px;font-size:12px;flex:1.5}"
        ".nw-key.correct{background:#38a169;color:#fff}"
        ".nw-key.present{background:#d69e2e;color:#fff}"
        ".nw-key.absent{background:#94a3b8;color:#fff}"
        ".nw-key:active{transform:translateY(1px)}"
        ".nw-panel{background:#fff;border:1px solid #dde4ef;border-radius:14px;padding:18px 20px;"
        "margin:18px 0;box-shadow:0 2px 10px rgba(0,0,0,.06);font-family:system-ui,sans-serif}"
        ".nw-reveal{background:#f0fff4;border:1px solid #9ae6b4;border-radius:14px;padding:18px 22px;"
        "margin:16px 0;font-family:system-ui,sans-serif;display:none}"
        ".nw-reveal.show{display:block}"
        ".nw-reveal h3{margin:0 0 6px;color:#22543d;font-size:19px}"
        ".nw-reveal p{margin:0 0 8px;font-size:14px;color:#276749;line-height:1.5}"
        ".nw-reveal a{color:#276749;font-weight:700;text-decoration:none}"
        ".nw-btn{background:#1a4d80;color:#fff;border:none;padding:9px 18px;border-radius:8px;"
        "font-size:14px;font-family:system-ui,sans-serif;cursor:pointer;font-weight:600}"
        ".nw-btn.ghost{background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80}"
        ".nw-rules{font-size:13px;color:#4a5568;line-height:1.6}"
        ".nw-rules b{color:#2d3748}"
        ".nw-swatch{display:inline-block;width:15px;height:15px;border-radius:3px;vertical-align:middle;margin:0 2px}"
        ".parent-note{background:#f0fff4;border:1px solid #9ae6b4;border-radius:12px;padding:16px 20px;"
        "margin:18px 0 0;font-family:system-ui,sans-serif}"
        ".parent-note strong{color:#22543d}"
        ".parent-note p{margin:6px 0 0;font-size:13px;color:#276749;line-height:1.55}"
        ".parent-note a{color:#276749;font-weight:600}"
        "@media(max-width:480px){.nw-tile{width:44px;height:44px;font-size:23px}.nw-key{height:46px}}"
        "@media(prefers-color-scheme:dark){.nw-tile{background:#1a202c;color:#e2e8f0;border-color:#2d3748}"
        ".nw-panel{background:#1a202c;border-color:#2d3748;color:#e2e8f0}"
        ".nw-rules{color:#a0aec0}.nw-rules b{color:#e2e8f0}.nw-key{background:#2d3748;color:#e2e8f0}}"
    )

    # ---- client JS (PLAIN string; contains all the braces) ----------------------
    # NOTE: placeholders __SECRET__ etc. are swapped for JSON literals afterward so the
    # JS body itself stays free of Python f-string interpolation.
    js = (
        "(function(){"
        "var SECRET=__SECRET__,VALID=__VALID__,WL=__WL__,MAXG=__MAXG__,"
        "SLUG=__SLUG__,TITLE=__TITLE__;"
        "var board=document.getElementById('nw-board'),msg=document.getElementById('nw-msg'),"
        "kb=document.getElementById('nw-kb'),reveal=document.getElementById('nw-reveal'),"
        "revealBody=document.getElementById('nw-reveal-body');"
        "if(!board)return;"
        "var row=0,col=0,cur='',done=false,grid=[],keyState={};"
        "for(var r=0;r<MAXG;r++){var rowEl=document.createElement('div');rowEl.className='nw-row';"
        "rowEl.style.gridTemplateColumns='repeat('+WL+',1fr)';var cells=[];"
        "for(var c=0;c<WL;c++){var t=document.createElement('div');t.className='nw-tile';"
        "t.id='nw-t-'+r+'-'+c;rowEl.appendChild(t);cells.push(t);}board.appendChild(rowEl);grid.push(cells);}"
        "var rows=['QWERTYUIOP','ASDFGHJKL','ZXCVBNM'];"
        "rows.forEach(function(letters,ri){var kr=document.createElement('div');kr.className='nw-kbrow';"
        "if(ri===2){kr.appendChild(mkKey('ENTER','enter',true));}"
        "letters.split('').forEach(function(ch){kr.appendChild(mkKey(ch,ch,false));});"
        "if(ri===2){kr.appendChild(mkKey('DEL','del',true));}kb.appendChild(kr);});"
        "function mkKey(label,val,wide){var b=document.createElement('button');b.type='button';"
        "b.className='nw-key'+(wide?' wide':'');b.textContent=label;b.setAttribute('data-k',val);"
        "b.setAttribute('aria-label',val==='del'?'delete':val==='enter'?'enter':'letter '+label);"
        "b.addEventListener('click',function(){handle(val);});return b;}"
        "function setMsg(s){msg.textContent=s||'';}"
        "function handle(k){if(done)return;"
        "if(k==='enter'){submit();return;}"
        "if(k==='del'){if(col>0){col--;cur=cur.slice(0,-1);paint();}setMsg('');return;}"
        "if(/^[A-Z]$/.test(k)&&col<WL){cur+=k;var t=grid[row][col];t.textContent=k;"
        "t.classList.add('filled','pop');(function(el){setTimeout(function(){el.classList.remove('pop');},120);})(t);"
        "col++;setMsg('');}}"
        "function paint(){for(var c=0;c<WL;c++){var t=grid[row][c];"
        "if(c<cur.length){t.textContent=cur[c];t.classList.add('filled');}"
        "else{t.textContent='';t.classList.remove('filled');}}}"
        "function score(guess){var res=new Array(WL).fill('absent');var counts={};var i,ch;"
        "for(i=0;i<WL;i++){ch=SECRET[i];counts[ch]=(counts[ch]||0)+1;}"
        "for(i=0;i<WL;i++){if(guess[i]===SECRET[i]){res[i]='correct';counts[guess[i]]--;}}"
        "for(i=0;i<WL;i++){if(res[i]==='correct')continue;ch=guess[i];"
        "if(counts[ch]>0){res[i]='present';counts[ch]--;}}return res;}"
        "function rank(a,b){var o={correct:3,present:2,absent:1};return (o[a]||0)-(o[b]||0);}"
        "function submit(){if(col<WL){setMsg('Not enough letters');return;}"
        "var guess=cur;if(VALID.indexOf(guess)===-1&&guess!==SECRET){setMsg('Try a real word');return;}"
        "var res=score(guess);"
        "for(var c=0;c<WL;c++){(function(idx){var t=grid[row][idx];"
        "setTimeout(function(){t.classList.add(res[idx]);},idx*90);"
        "var kbtn=kb.querySelector('[data-k=\"'+guess[idx]+'\"]');"
        "if(kbtn){var prev=keyState[guess[idx]];if(rank(res[idx],prev)>0||!prev){"
        "if(prev)kbtn.classList.remove(prev);kbtn.classList.add(res[idx]);keyState[guess[idx]]=res[idx];}}"
        "})(c);}"
        "if(guess===SECRET){done=true;setTimeout(function(){setMsg('You got it! Nice work.');win();},WL*90+120);return;}"
        "row++;col=0;cur='';"
        "if(row>=MAXG){done=true;setTimeout(function(){setMsg('Out of guesses — the word was '+SECRET);lose();},WL*90+120);}"
        "else{setMsg('');}}"
        "function win(){showReveal(true);}"
        "function lose(){showReveal(false);}"
        "function showReveal(won){"
        "var h=won?'\\uD83C\\uDF89 You solved today\\u2019s News Word!':'\\uD83D\\uDCD6 The word was '+SECRET;"
        "var body='<h3>'+h+'</h3>';"
        "body+='<p>The word <b>'+SECRET+'</b> came from a real story we shared for curious kids.</p>';"
        "if(SLUG){body+='<p><a href=\"/'+SLUG+'\">Read the story: '+esc(TITLE)+' \\u2192</a></p>';}"
        "else{body+='<p>Come back tomorrow for a brand-new science word!</p>';}"
        "body+='<p style=\"font-size:12px;color:#718096\">Everything you played stayed on your device \\u2014 nothing was uploaded.</p>';"
        "revealBody.innerHTML=body;reveal.classList.add('show');}"
        "function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}"
        "document.addEventListener('keydown',function(e){if(done)return;"
        "if(e.target&&(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA'))return;"
        "var k=e.key;if(k==='Enter'){handle('enter');}else if(k==='Backspace'){handle('del');}"
        "else if(/^[a-zA-Z]$/.test(k)){handle(k.toUpperCase());}});"
        "})();"
    )
    js = (js.replace("__SECRET__", secret_js).replace("__VALID__", valid_js)
            .replace("__WL__", wl_js).replace("__MAXG__", max_js)
            .replace("__SLUG__", slug_js).replace("__TITLE__", title_js))

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>News Word — Daily Science Word Game — KiddieDaily</title>
<meta name="description" content="News Word is a free daily word-guessing game for kids. The secret word is a real science or nature term from the day's headlines — guess it in six tries, then read the story behind it.">
<meta property="og:title" content="News Word — KiddieDaily's Daily Science Word Game">
<meta property="og:description" content="Guess the hidden science word in six tries with green/yellow/gray hints, then discover the real headline it came from. Free, kid-safe, no sign-up.">
<meta property="og:url" content="https://kiddiedaily.com/news-word/">
<meta property="og:image" content="https://kiddiedaily.com/og-science.svg">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="https://kiddiedaily.com/news-word/">
{CSS}
<style>{page_css}</style>
</head><body>
{HEADER}
<main id="main" style="max-width:820px;margin:0 auto;padding:28px 24px 64px">
<div class="nw-hero">
<h1>&#129504; News Word</h1>
<p>Today&rsquo;s secret word is a real science or nature term from {hint_label}. Guess it in six tries &mdash; green means right spot, yellow means right letter/wrong spot. Solve it to unlock the story behind the word!</p>
</div>
<div id="nw-msg" class="nw-msg"></div>
<div id="nw-board" class="nw-board" role="grid" aria-label="News Word guessing board"></div>
<div id="nw-kb" class="nw-kb" aria-label="On-screen keyboard"></div>
<div id="nw-reveal" class="nw-reveal" aria-live="polite"><div id="nw-reveal-body"></div>
<div style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap">
<a href="/news/today.html" class="nw-btn" style="text-decoration:none">Today&rsquo;s news</a>
<a href="/games/" class="nw-btn ghost" style="text-decoration:none">More games</a>
</div></div>
<div class="nw-panel">
<div class="nw-rules">
<b>How to play</b><br>
Type a {wl}-letter word and press Enter. After each guess the tiles change color:<br>
<span class="nw-swatch" style="background:#38a169"></span> <b>Green</b> = right letter, right spot.
<span class="nw-swatch" style="background:#d69e2e"></span> <b>Yellow</b> = right letter, wrong spot.
<span class="nw-swatch" style="background:#94a3b8"></span> <b>Gray</b> = that letter isn&rsquo;t in the word.<br>
You get <b>six</b> guesses. The answer is always a word from a real, kid-friendly science or nature story &mdash; no scary or grown-up news here.
</div>
</div>
<div class="parent-note">
<strong>&#129504; For grown-ups</strong>
<p>News Word is a Wordle-style vocabulary game where the daily answer is a genuine science or nature word pulled from that day&rsquo;s kid-safe headlines. It builds spelling, pattern-thinking, and curiosity &mdash; and every solved word links to the real story so learning keeps going.</p>
<p>It runs entirely in the browser: no accounts, no cookies, nothing your child types is ever uploaded. Looking for more? Try our <a href="/games/">Games</a> and <a href="/draw/">Draw the News</a> pages.</p>
</div>
<div style="margin-top:20px;display:flex;gap:10px;flex-wrap:wrap">
<a href="/news/science.html" class="nw-btn ghost" style="text-decoration:none">More science stories</a>
<a href="/news/" class="nw-btn ghost" style="text-decoration:none">All kid news</a>
</div>
</main>
{FOOTER}
<script>{js}</script>
</body></html>"""

    upload("news-word/index.html", page, "[scraper] News Word daily science word game")
    print(f"  News Word page: secret is a {wl}-letter word from a real headline (pool of {len(pool)} candidates)")


def generate_time_traveler_page(manifest, today):
    """Generate /time-traveler/index.html — an era timeline of history stories.

    Places recent history / archaeology / ancient-world stories onto a visual
    'time traveler' timeline by the era they discuss (Ancient, Medieval,
    Renaissance, Modern) using keyword detection on the title + description.
    Kids browse the past by *when it happened*, not just the flat history feed.

    Static + privacy-safe: no backend, no cookies, no trackers, no external
    model APIs. The era filter is client-side only (in-page JS). Deterministic:
    era assignment and ordering depend only on the corpus, so identical inputs
    produce identical HTML (no random / time-of-day churn).
    """
    articles = manifest.get("articles", [])

    # Only surface visual / kid-safe stories — never world/politics. History is
    # the spine, but we also let clearly historical science/archaeology pieces in.
    ALLOWED_CATS = {"history", "science", "space", "animals", "environment"}

    # Defense-in-depth: in this manifest EVERY non-science article carries a base
    # "world" cat, so a history-tagged story is often cats={"world","history"}.
    # We therefore CANNOT exclude on the "world" cat (it would drop most real
    # history pieces). Instead, reject any story whose text carries hard
    # politics / conflict / crime language even if it matched an era keyword, so
    # the page honors its "no world/politics" promise for ages 8-12.
    BLOCK_KW = (
        "president", "senator", "congress", "election", "vote", "voter",
        "ballot", "campaign", "democrat", "republican", "politic", "parliament",
        "prime minister", "protest", "riot", "coup", "sanction", "tariff",
        "war ", "warfare", "wartime", "world war", "civil war", "invasion",
        "invade", "troops", "military", "missile", "airstrike", "air strike",
        "bomb", "shooting", "shooter", "gun ", "weapon", "terror", "hostage",
        "killed", "killing", "murder", "assault", "genocide", "massacre",
        "refugee", "migrant", "deport", "immigration", "indict", "felony",
        "lawsuit", "verdict", "prison", "arrest", "scandal", "corruption",
        "shutdown", "impeach", "nuclear weapon", "ceasefire", "hamas", "israel",
        "ukraine", "russia", "gaza", "trump", "biden", "putin",
    )

    def _text(a):
        return " ".join([
            a.get("display_title", "") or a.get("title", "") or "",
            a.get("description", "") or "",
        ]).lower()

    def _blocked(a):
        # Whole-substring check on title+description. Deterministic; text-only.
        txt = _text(a)
        return any(b in txt for b in BLOCK_KW)

    def _kid_safe(a):
        cats = set(a.get("cats") or [])
        # Hard reject: politics / conflict / crime language is never appropriate,
        # even for a story that also carries the history cat.
        if _blocked(a):
            return False
        # Must have at least one allowed visual cat OR be flagged science.
        if "history" in cats:
            return True
        if not (cats & ALLOWED_CATS or a.get("is_science")):
            return False
        # A history-adjacent story still needs historical language to earn a spot.
        return True

    # ── Era detection ──────────────────────────────────────────────────────────
    # Ordered oldest -> newest. Each era carries keyword triggers; matching is
    # done as whole-word-ish substring checks against title+description.
    ERAS = [
        {
            "key": "ancient",
            "name": "Ancient World",
            "span": "Before 500 CE",
            "icon": "\U0001F3FA",  # amphora
            "color": "#b7791f",
            "tint": "#fffaf0",
            "line": "Pyramids, pharaohs, and the first great cities.",
            "kw": ["ancient", "egypt", "pharaoh", "pyramid", "mummy", "mummies",
                   "pharaohs", "roman", "rome", "greek", "greece", "mesopotamia",
                   "sumer", "babylon", "bronze age", "iron age", "stone age",
                   "prehistoric", "neolithic", "fossil", "dinosaur", "mammoth",
                   "cave painting", "hieroglyph", "aztec", "maya", "mayan",
                   "inca", "bce", "b.c.", "antiquity", "pompeii", "gladiator",
                   "pharaonic", "sphinx", "archaeolog", "excavat", "artifact",
                   "artefact", "ruins", "tomb", "temple", "millennia",
                   "thousands of years", "years ago"],
        },
        {
            "key": "medieval",
            "name": "Medieval Times",
            "span": "500 - 1400 CE",
            "icon": "\U0001F3F0",  # castle
            "color": "#805ad5",
            "tint": "#faf5ff",
            "line": "Castles, knights, and kingdoms across the world.",
            "kw": ["medieval", "middle ages", "knight", "castle", "viking",
                   "vikings", "crusade", "crusades", "monk", "monastery",
                   "dynasty", "samurai", "feudal", "plague", "black death",
                   "cathedral", "kingdom", "empire of", "byzantine", "moat",
                   "chivalry", "longbow", "sword", "shield maiden", "norse",
                   "anglo-saxon", "sultan", "caliph"],
        },
        {
            "key": "renaissance",
            "name": "Age of Discovery",
            "span": "1400 - 1750 CE",
            "icon": "\U0001F5FA",  # world map
            "color": "#2f855a",
            "tint": "#f0fff4",
            "line": "Explorers, inventors, and new ideas set sail.",
            "kw": ["renaissance", "explorer", "explorers", "voyage", "galleon",
                   "shipwreck", "columbus", "magellan", "da vinci", "leonardo",
                   "telescope", "galileo", "printing press", "colonial",
                   "conquistador", "17th century", "16th century", "1500s",
                   "1600s", "age of sail", "new world", "circumnavigat",
                   "cartograph", "astrolabe"],
        },
        {
            "key": "modern",
            "name": "Modern Era",
            "span": "1750 CE - today",
            "icon": "⚙️",  # gear
            "color": "#2b6cb0",
            "tint": "#ebf8ff",
            "line": "Machines, flight, and world-changing discoveries.",
            "kw": ["industrial", "revolution", "steam engine", "victorian",
                   "1800s", "1900s", "19th century", "20th century", "world war",
                   "wwi", "wwii", "titanic", "wright brothers", "moon landing",
                   "apollo", "cold war", "railway", "railroad", "locomotive",
                   "invention", "electricity", "photograph", "automobile",
                   "aviation", "shackleton", "expedition", "century ago",
                   "decades ago", "1920s", "1940s", "1960s"],
        },
    ]
    ERA_INDEX = {e["key"]: i for i, e in enumerate(ERAS)}

    def _era_for(a):
        """Return era key, or None if no historical era keyword matched.

        Scores every era by keyword hits; ties break toward the OLDER era so a
        piece mentioning both 'ancient' and 'modern dating' reads as ancient.
        Deterministic: depends only on the text.
        """
        txt = _text(a)
        best_key, best_score = None, 0
        for e in ERAS:
            score = 0
            for k in e["kw"]:
                if k in txt:
                    score += 1
            if score > best_score:
                best_score = score
                best_key = e["key"]
        return best_key

    # ── Build the timeline buckets ─────────────────────────────────────────────
    # Use the TAIL for "recent"; scan newest-first so each era shows fresh finds.
    pool = [a for a in articles if _kid_safe(a)]
    recent = list(reversed(pool[-140:] if len(pool) >= 140 else pool))

    DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

    def _pub_date(a):
        m = DATE_RE.search(a.get("slug", "") or "")
        return m.group(0) if m else ""

    MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    def _pretty_date(d):
        m = DATE_RE.match(d) if d else None
        if not m:
            return ""
        y, mo, da = m.group(1), int(m.group(2)), int(m.group(3))
        mo = MONTHS[mo] if 1 <= mo <= 12 else ""
        return (mo + " " + str(da) + ", " + y).strip()

    # Assign each recent story to at most one era; de-duplicate by slug.
    buckets = {e["key"]: [] for e in ERAS}
    seen = set()
    PER_ERA = 8  # cap per era so the page stays scannable + deterministic
    for a in recent:
        slug = a.get("slug", "")
        if not slug or slug in seen:
            continue
        key = _era_for(a)
        if key is None:
            continue
        if len(buckets[key]) >= PER_ERA:
            continue
        seen.add(slug)
        buckets[key].append(a)

    total_placed = sum(len(v) for v in buckets.values())

    # Fallback content if the corpus has no clearly-dated history stories yet.
    if total_placed == 0:
        empty_state = (
            '<div class="tt-empty">'
            '<div class="tt-empty-ic">\U0001F9ED</div>'
            '<p>The time machine is warming up! We haven’t spotted enough '
            'history stories in today’s news yet. Check back soon — '
            'new discoveries from the past land here all the time.</p>'
            '<a href="/news/history.html">Browse all history stories &rarr;</a>'
            '</div>'
        )
    else:
        empty_state = ""

    # ── Era chips (client-side filter buttons) ─────────────────────────────────
    def _esc(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    chips = ['<button class="tt-chip tt-chip-all sel" data-era="all">'
             '\U0001F30D All eras</button>']
    for e in ERAS:
        n = len(buckets[e["key"]])
        disabled = "" if n else " tt-chip-off"
        chips.append(
            '<button class="tt-chip' + disabled + '" data-era="' + e["key"] + '" '
            'style="--tt-c:' + e["color"] + '">'
            + e["icon"] + ' ' + _esc(e["name"])
            + ' <span class="tt-chip-n">' + str(n) + '</span></button>'
        )
    chips_html = "".join(chips)

    # ── Timeline sections ──────────────────────────────────────────────────────
    sections = []
    for e in ERAS:
        items = buckets[e["key"]]
        cards = []
        for a in items:
            title = _esc(a.get("display_title", "") or a.get("title", ""))
            desc = a.get("description", "") or ""
            if len(desc) > 150:
                desc = desc[:147].rstrip() + "…"
            desc = _esc(desc)
            slug = a.get("slug", "")
            # Attribute-safe: slugs are build-generated, but escape defensively so
            # a stray quote/angle bracket can never break the href or inject markup.
            slug_attr = _esc(slug).replace('"', "&quot;")
            d = _pub_date(a)
            pretty = _esc(_pretty_date(d))
            date_html = ('<span class="tt-when">' + pretty + '</span>') if pretty else ""
            cards.append(
                '<article class="tt-card">'
                + date_html
                + '<h3><a href="/' + slug_attr + '">' + title + '</a></h3>'
                + ('<p>' + desc + '</p>' if desc else "")
                + '<a class="tt-read" href="/' + slug_attr + '">Read this story &rarr;</a>'
                + '</article>'
            )
        cards_html = "".join(cards)
        if not cards_html:
            # Keep the era on the map but show a gentle placeholder.
            cards_html = ('<p class="tt-none">No stories from this era in today’s '
                          'news — the timeline refreshes as new finds arrive.</p>')
        sections.append(
            '<section class="tt-era" data-era="' + e["key"] + '" '
            'style="--tt-c:' + e["color"] + ';--tt-tint:' + e["tint"] + '">'
            '<div class="tt-era-head">'
            '<span class="tt-dot"></span>'
            '<div class="tt-era-title">'
            '<span class="tt-era-ic">' + e["icon"] + '</span>'
            '<h2>' + _esc(e["name"]) + '</h2>'
            '<span class="tt-span">' + _esc(e["span"]) + '</span>'
            '</div></div>'
            '<p class="tt-era-line">' + _esc(e["line"]) + '</p>'
            '<div class="tt-cards">' + cards_html + '</div>'
            '</section>'
        )
    sections_html = "".join(sections)

    # ── Page-specific CSS (PLAIN string — no f-string, no literal-brace traps) ──
    page_css = (
        ".tt-hero{background:linear-gradient(135deg,#1a4d80,#2b6cb0);color:#fff;"
        "border-radius:16px;padding:26px 26px;margin:0 0 20px;font-family:system-ui,sans-serif}"
        ".tt-hero h1{margin:0 0 6px;font-size:30px}"
        ".tt-hero p{margin:0;font-size:15px;color:#dbeafe;line-height:1.5}"
        ".tt-bar{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 22px;font-family:system-ui,sans-serif}"
        ".tt-chip{background:#fff;border:1.5px solid #cbd5e0;color:#2d3748;border-radius:999px;"
        "padding:7px 14px;font-size:13px;font-weight:600;cursor:pointer;line-height:1.2;"
        "display:inline-flex;align-items:center;gap:6px}"
        ".tt-chip:hover{border-color:var(--tt-c,#1a4d80)}"
        ".tt-chip.sel{background:var(--tt-c,#1a4d80);border-color:var(--tt-c,#1a4d80);color:#fff}"
        ".tt-chip-all.sel{background:#1a4d80;border-color:#1a4d80}"
        ".tt-chip-n{background:rgba(0,0,0,.10);border-radius:999px;padding:0 7px;font-size:11px;"
        "min-width:18px;text-align:center}"
        ".tt-chip.sel .tt-chip-n{background:rgba(255,255,255,.25)}"
        ".tt-chip-off{opacity:.4;cursor:not-allowed}"
        ".tt-line{position:relative;padding-left:26px}"
        ".tt-line:before{content:'';position:absolute;left:7px;top:6px;bottom:6px;width:3px;"
        "background:linear-gradient(180deg,#b7791f,#805ad5,#2f855a,#2b6cb0);border-radius:3px}"
        ".tt-era{position:relative;margin:0 0 30px;scroll-margin-top:70px}"
        ".tt-era-head{display:flex;align-items:center;gap:10px;margin:0 0 4px}"
        ".tt-dot{position:absolute;left:-26px;top:4px;width:17px;height:17px;border-radius:50%;"
        "background:var(--tt-c,#1a4d80);border:3px solid #faf8f3;box-shadow:0 0 0 2px var(--tt-c,#1a4d80)}"
        ".tt-era-title{display:flex;align-items:baseline;flex-wrap:wrap;gap:8px}"
        ".tt-era-ic{font-size:22px}"
        ".tt-era-title h2{margin:0;font-size:22px;color:var(--tt-c,#1a4d80);border:none;padding:0}"
        ".tt-span{font-size:12px;font-weight:700;color:#718096;font-family:system-ui,sans-serif;"
        "text-transform:uppercase;letter-spacing:1px}"
        ".tt-era-line{margin:0 0 12px;font-size:14px;color:#4a5568;font-family:system-ui,sans-serif;font-style:italic}"
        ".tt-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}"
        ".tt-card{background:var(--tt-tint,#fff);border:1px solid #e2e8f0;border-left:4px solid var(--tt-c,#1a4d80);"
        "border-radius:10px;padding:14px 16px;font-family:system-ui,sans-serif;display:flex;flex-direction:column}"
        ".tt-when{font-size:11px;font-weight:700;color:var(--tt-c,#1a4d80);text-transform:uppercase;"
        "letter-spacing:.5px;margin:0 0 4px}"
        ".tt-card h3{margin:0 0 6px;font-size:16px;line-height:1.35;font-family:Georgia,serif}"
        ".tt-card h3 a{color:#1a2b44}"
        ".tt-card p{margin:0 0 10px;font-size:13px;color:#4a5568;line-height:1.5;flex:1}"
        ".tt-read{font-size:13px;color:var(--tt-c,#2b6cb0);font-weight:600;text-decoration:none}"
        ".tt-read:hover{text-decoration:underline}"
        ".tt-none{font-size:13px;color:#a0aec0;font-family:system-ui,sans-serif;margin:0;padding:8px 0}"
        ".tt-empty{background:#fff;border:1px dashed #cbd5e0;border-radius:14px;padding:28px 24px;"
        "text-align:center;font-family:system-ui,sans-serif;color:#4a5568}"
        ".tt-empty-ic{font-size:34px;margin-bottom:8px}"
        ".tt-empty a{display:inline-block;margin-top:10px;color:#2b6cb0;font-weight:600;text-decoration:none}"
        ".tt-note{background:#f0f4f8;border:1px solid #d6e0ea;border-radius:12px;padding:14px 18px;"
        "margin:6px 0 0;font-family:system-ui,sans-serif;font-size:13px;color:#4a5568;line-height:1.55}"
        ".tt-note strong{color:#1a4d80}"
        ".tt-cta{margin-top:22px;display:flex;gap:10px;flex-wrap:wrap}"
        ".tt-cta a{padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif}"
        "@media(prefers-color-scheme:dark){"
        ".tt-chip{background:#1a202c;border-color:#2d3748;color:#e2e8f0}"
        ".tt-card{background:#161b26;border-color:#2d3748}"
        ".tt-card h3 a{color:#cfe0f5}"
        ".tt-dot{border-color:#0f1117}"
        ".tt-empty{background:#161b26;border-color:#2d3748;color:#a0aec0}"
        ".tt-note{background:#161b26;border-color:#2d3748;color:#a0aec0}}"
    )

    # ── Client JS (PLAIN string) — era filter, no data leaves the browser ──────
    page_js = (
        "(function(){"
        "var bar=document.getElementById('tt-bar');if(!bar)return;"
        "var chips=bar.querySelectorAll('.tt-chip');"
        "var eras=document.querySelectorAll('.tt-era');"
        "function apply(sel){"
        "for(var i=0;i<eras.length;i++){"
        "var k=eras[i].getAttribute('data-era');"
        "eras[i].style.display=(sel==='all'||sel===k)?'':'none';}"
        "for(var j=0;j<chips.length;j++){"
        "chips[j].classList.toggle('sel',chips[j].getAttribute('data-era')===sel);}}"
        "for(var c=0;c<chips.length;c++){(function(btn){"
        "if(btn.classList.contains('tt-chip-off'))return;"
        "btn.addEventListener('click',function(){"
        "var sel=btn.getAttribute('data-era');apply(sel);"
        "if(sel!=='all'){var t=document.querySelector('.tt-era[data-era=\"'+sel+'\"]');"
        "if(t&&t.scrollIntoView)t.scrollIntoView({behavior:'smooth',block:'start'});}"
        "});})(chips[c]);}"
        "})();"
    )

    # ── Page shell (f-string with ZERO literal { } braces) ─────────────────────
    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Time Traveler — KiddieDaily History Timeline</title>
<meta name="description" content="Travel through history! KiddieDaily sorts real history and archaeology stories onto a timeline by era — Ancient, Medieval, Age of Discovery, and Modern. Browse the past by when it happened.">
<meta property="og:title" content="Time Traveler — KiddieDaily History Timeline">
<meta property="og:description" content="Real history stories placed on a timeline by era. Browse the past by when it happened — a free history explorer for curious kids.">
<meta property="og:url" content="https://kiddiedaily.com/time-traveler/">
<meta property="og:image" content="https://kiddiedaily.com/og-science.svg">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="https://kiddiedaily.com/time-traveler/">
{CSS}
<style>{page_css}</style>
</head><body>
{HEADER}
<main id="main" style="max-width:820px;margin:0 auto;padding:28px 24px 64px">
<div class="tt-hero">
<h1>&#9203; Time Traveler</h1>
<p>Hop in the time machine! We take real history and archaeology stories from the news and place them on a timeline by the era they explore. Tap an era to jump through the past.</p>
</div>
<div class="tt-bar" id="tt-bar">{chips_html}</div>
{empty_state}
<div class="tt-line">
{sections_html}
</div>
<div class="tt-note">
<strong>&#128218; How the timeline works:</strong> We read each story&#39;s headline and summary and look for clues about <em>when</em> it happened &mdash; words like &ldquo;pyramid,&rdquo; &ldquo;castle,&rdquo; &ldquo;explorer,&rdquo; or &ldquo;steam engine.&rdquo; Then we drop it into the matching era. It&#39;s a fun estimate, not a history exam &mdash; a great way to start a conversation about how long ago things really happened!
</div>
<div class="tt-cta">
<a href="/news/history.html" style="background:#1a4d80;color:#fff">All history stories</a>
<a href="/draw/" style="background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80">Draw the news</a>
<a href="/games/" style="background:#f7fafc;color:#718096;border:1px solid #e2e8f0">Games &amp; quizzes</a>
</div>
</main>
{FOOTER}
<script>{page_js}</script>
</body></html>"""

    upload("time-traveler/index.html", page, "[scraper] Time Traveler history era timeline")
    placed_bits = ", ".join(e["name"] + ":" + str(len(buckets[e["key"]])) for e in ERAS)
    print(f"  Time Traveler page: {total_placed} stories placed across 4 eras ({placed_bits})")


def generate_search_page(manifest):
    """Generate /search.html — full-page search interface fetching /data/kd-articles.json."""
    articles = manifest.get("articles", [])
    total = len(articles)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Search — KiddieDaily</title>
<meta name="description" content="Search all KiddieDaily news articles — kid-friendly, bias-rated, fact-checked.">
<meta property="og:title" content="Search — KiddieDaily">
<meta property="og:description" content="Search 700+ kid-safe, bias-rated news articles. Filter by science, space, animals, and more.">
<meta property="og:url" content="https://kiddiedaily.com/search.html">
<meta property="og:image" content="https://kiddiedaily.com/og-science.svg">
<meta name="twitter:card" content="summary">
<link rel="canonical" href="https://kiddiedaily.com/search.html">
<link rel="alternate" type="application/rss+xml" title="KiddieDaily RSS" href="/feed.xml">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"WebSite","name":"KiddieDaily","url":"https://kiddiedaily.com","potentialAction":{{"@type":"SearchAction","target":{{"@type":"EntryPoint","urlTemplate":"https://kiddiedaily.com/search.html?q={{search_term_string}}"}},"query-input":"required name=search_term_string"}}}}</script>
{CSS}
<style>
#kd-search-input{{
  display:block;width:100%;box-sizing:border-box;
  font-size:22px;padding:14px 18px;
  border:2px solid #1a4d80;border-radius:10px;
  font-family:system-ui,sans-serif;color:#1a1a1a;
  background:#fff;margin-bottom:8px;
  box-shadow:0 2px 8px rgba(26,77,128,.10);
  outline:none;
}}
#kd-search-input:focus{{border-color:#ffd700;box-shadow:0 2px 12px rgba(26,77,128,.18)}}
#kd-result-count{{font-size:14px;color:#718096;font-family:system-ui,sans-serif;margin:0 0 20px;min-height:20px}}
.kd-sr{{background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:14px 18px 12px;margin:8px 0;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.kd-sr-top{{display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap}}
.kd-sr h3{{margin:4px 0 4px;font-size:1em;line-height:1.35}}
.kd-sr h3 a{{color:#1a4d80;text-decoration:none}}
.kd-sr h3 a:hover{{text-decoration:underline}}
.kd-sr-meta{{font-size:12px;color:#a0aec0;margin-top:4px;font-family:system-ui,sans-serif}}
.kd-badge{{font-size:10px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;padding:2px 8px;border-radius:20px}}
.kd-badge-sci{{background:#d1fae5;color:#065f46}}
.kd-badge-news{{background:#dbeafe;color:#1e40af}}
#kd-no-results{{display:none;text-align:center;color:#718096;font-family:system-ui,sans-serif;padding:40px 0;font-size:15px}}
.kd-cat-filters{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}}
.kd-cat-btn{{padding:7px 16px;border-radius:20px;border:2px solid #dde4ef;background:#fff;
  font-size:13px;font-weight:700;cursor:pointer;font-family:system-ui,sans-serif;
  color:#4a5568;transition:all .15s}}
.kd-cat-btn.active{{background:#1a4d80;color:#fff;border-color:#1a4d80}}
.kd-cat-btn:hover:not(.active){{border-color:#1a4d80;color:#1a4d80}}
</style>
</head>
<body>
{{HEADER}}
<main id="main" style="max-width:780px;margin:0 auto;padding:32px 24px 64px">
<h1 style="font-size:28px;margin:0 0 16px">Search KiddieDaily</h1>
<div class="kd-cat-filters">
  <button class="kd-cat-btn active" data-cat="all" onclick="setCat(this,'all')">All</button>
  <button class="kd-cat-btn" data-cat="science" onclick="setCat(this,'science')">&#128300; Science</button>
  <button class="kd-cat-btn" data-cat="world" onclick="setCat(this,'world')">&#127758; World</button>
  <button class="kd-cat-btn" data-cat="space" onclick="setCat(this,'space')">&#128640; Space</button>
  <button class="kd-cat-btn" data-cat="animals" onclick="setCat(this,'animals')">&#128062; Animals</button>
  <button class="kd-cat-btn" data-cat="history" onclick="setCat(this,'history')">&#127963; History</button>
  <button class="kd-cat-btn" data-cat="environment" onclick="setCat(this,'environment')">&#127807; Env</button>
  <button class="kd-cat-btn" data-cat="technology" onclick="setCat(this,'technology')">&#128187; Tech</button>
</div>
<input
  id="kd-search-input"
  type="search"
  placeholder="Search {total} articles..."
  aria-label="Search articles"
  autofocus
  autocomplete="off"
  spellcheck="false"
>
<p id="kd-result-count"></p>
<div id="kd-results"></div>
<div id="kd-no-results">No articles matched your search.</div>
<p style="text-align:center;margin-top:32px;font-size:13px;color:#718096;font-family:system-ui,sans-serif">
  <a href="/news/archive.html" style="color:#1a4d80">Full archive</a> &middot;
  <a href="/news/" style="color:#1a4d80">Kid News</a> &middot;
  <a href="/feed.xml" style="color:#1a4d80">RSS</a>
</p>
</main>
{{FOOTER}}
<script>
(function(){{
  var container = document.getElementById('kd-results');
  var countEl   = document.getElementById('kd-result-count');
  var noResults = document.getElementById('kd-no-results');
  var input     = document.getElementById('kd-search-input');
  var allArticles = [];
  var activeCategory = 'all';
  var MO=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  var TODAY_STR=new Date().toISOString().slice(0,10);
  function fmtDate(d){{var p=d?d.split('-'):[];return p.length===3?MO[parseInt(p[1])-1]+' '+parseInt(p[2])+', '+p[0]:d||'';}}

  function setCat(btn, cat) {{
    activeCategory = cat;
    document.querySelectorAll('.kd-cat-btn').forEach(function(b) {{ b.classList.remove('active'); }});
    btn.classList.add('active');
    filterAndRender();
  }}
  window.setCat = setCat;

  function renderResults(articles, query) {{
    if (!articles.length) {{
      container.innerHTML = '';
      noResults.style.display = (query || activeCategory !== 'all') ? 'block' : 'none';
      countEl.textContent = '';
      return;
    }}
    noResults.style.display = 'none';
    if (query) {{
      countEl.textContent = articles.length + ' result' + (articles.length === 1 ? '' : 's') + " for '" + query + "'";
    }} else {{
      countEl.textContent = articles.length + ' article' + (articles.length === 1 ? '' : 's') + ', newest first';
    }}
    container.innerHTML = articles.map(function(a) {{
      var badgeCls  = a.is_science ? 'kd-badge-sci' : 'kd-badge-news';
      var badgeLbl  = a.is_science ? 'Science' : 'World News';
      var src_word  = a.n_sources === 1 ? '1 source' : a.n_sources + ' sources';
      var excerpt = a.description ? '<p style="font-size:13px;color:#4a5568;margin:4px 0 6px;line-height:1.5">' + a.description.slice(0, 130) + (a.description.length > 130 ? '…' : '') + '</p>' : '';
      var cats=(a.cats||[]).filter(function(c){{return c!=='science'&&c!=='world';}});
      var catTags=cats.slice(0,2).map(function(c){{return '<span class="kd-badge" style="background:#e0e7ff;color:#3730a3;font-size:9px">'+c+'</span>';}}).join('');
      var newBadge=a.date===TODAY_STR?'<span class="kd-badge" style="background:#dc2626;color:#fff;margin-left:4px">NEW</span>':'';
      return '<div class="kd-sr">'
        + '<div class="kd-sr-top">'
        + '<span class="kd-badge ' + badgeCls + '">' + badgeLbl + '</span>'
        + catTags + newBadge
        + '</div>'
        + '<h3><a href="/' + a.slug + '">' + a.title + '</a></h3>'
        + excerpt
        + '<div class="kd-sr-meta">' + fmtDate(a.date) + ' &middot; ' + src_word + '</div>'
        + '</div>';
    }}).join('');
  }}

  function matchesCat(a, cat) {{
    if (cat === 'all') return true;
    if (cat === 'science') return a.is_science;
    if (cat === 'world') return !a.is_science;
    return (a.cats || []).indexOf(cat) !== -1;
  }}

  function filterAndRender() {{
    var q = input.value.trim().toLowerCase();
    var filtered = allArticles.filter(function(a) {{
      var catOk = matchesCat(a, activeCategory);
      var qOk   = !q || a.title.toLowerCase().indexOf(q) !== -1 || (a.description && a.description.toLowerCase().indexOf(q) !== -1);
      return catOk && qOk;
    }});
    renderResults(filtered, q);
  }}

  fetch('/data/kd-articles.json')
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
      allArticles = data.sort(function(a, b) {{ return b.date < a.date ? -1 : b.date > a.date ? 1 : 0; }});
      // Update placeholder with live count
      input.placeholder = 'Search ' + allArticles.length + ' articles...';
      // Pre-fill from ?q= URL parameter (enables Google sitelinks search box)
      var urlQ = new URLSearchParams(window.location.search).get('q') || '';
      if (urlQ) {{ input.value = urlQ; filterAndRender(); }}
      else {{ renderResults(allArticles, ''); }}
    }})
    .catch(function() {{
      countEl.textContent = 'Could not load articles. Try refreshing.';
    }});

  input.addEventListener('input', function() {{
    filterAndRender();
    // Keep URL in sync so searches are shareable
    var q = input.value.trim();
    var newUrl = q ? '?q=' + encodeURIComponent(q) : location.pathname;
    history.replaceState(null, '', newUrl);
  }});
  // Press / to focus the search box (skip if already typing somewhere)
  document.addEventListener('keydown', function(e) {{
    if (e.key === '/' && document.activeElement !== input && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {{
      e.preventDefault();
      input.focus();
    }}
  }});
}})();
</script>
</body></html>"""

    # Substitute HEADER and FOOTER (they contain braces so we inject after f-string render)
    page = page.replace('{HEADER}', HEADER).replace('{FOOTER}', FOOTER)
    upload("search.html", page, f"[scraper] Search page — {total} articles indexed")
    print(f"  Search page: {total} articles indexed")


# ── Saved Stories page ───────────────────────────────────────────────────────
def generate_saved_page():
    """Generate /saved.html — pure localStorage bookmark list, fetches /data/kd-articles.json."""
    page = """<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Saved Stories — KiddieDaily</title>
<meta name="description" content="Your saved KiddieDaily stories — bookmark articles to read later.">
<meta property="og:title" content="Saved Stories — KiddieDaily">
<meta property="og:url" content="https://kiddiedaily.com/saved.html">
<link rel="canonical" href="https://kiddiedaily.com/saved.html">
""" + CSS + """
</head><body>""" + HEADER + """
<main id="main" class="container" style="max-width:860px;margin:0 auto;padding:24px 16px">
<h1 style="font-size:26px;color:#1a4d80;margin-bottom:4px">🔖 Saved Stories</h1>
<p style="color:#718096;font-size:14px;margin-bottom:20px">Articles you've bookmarked for later — stored in your browser only.</p>
<div id="kd-saved-list"><p style="color:#718096">Loading your saved stories…</p></div>
<p style="margin-top:28px;font-size:13px;color:#a0aec0">Bookmarks are stored in your browser and are private to you.<br>
<a href="/news/" style="color:#1a4d80">Browse today's news &rarr;</a></p>
</main>""" + FOOTER + """
<script>
(function(){
  var KEY='kd_saved';
  var saved=JSON.parse(localStorage.getItem(KEY)||'[]');
  var el=document.getElementById('kd-saved-list');
  if(!saved.length){
    el.innerHTML='<div style="text-align:center;padding:40px 20px;color:#718096;font-family:system-ui,sans-serif">'
      +'<div style="font-size:48px;margin-bottom:12px">🔖</div>'
      +'<p style="font-size:16px;font-weight:600;margin-bottom:8px">No saved stories yet</p>'
      +'<p style="font-size:14px">When you read an article, tap <strong>🔖 Save</strong> to bookmark it here.</p>'
      +'<a href="/news/" style="display:inline-block;margin-top:16px;background:#1a4d80;color:#fff;padding:9px 20px;border-radius:6px;text-decoration:none;font-size:14px">Browse today\'s news</a>'
      +'</div>';
    return;
  }
  fetch('/data/kd-articles.json')
    .then(function(r){return r.json();})
    .then(function(data){
      var articles=data.articles||data;
      var bySlug={};
      articles.forEach(function(a){bySlug[a.slug]=a;});
      var found=saved.map(function(s){return bySlug[s];}).filter(Boolean);
      var missing=saved.filter(function(s){return !bySlug[s];});
      if(!found.length){
        el.innerHTML='<p style="color:#718096;font-size:14px">None of your saved articles could be found — they may have been removed. <a href="/news/" style="color:#1a4d80">Browse news</a></p>';
        return;
      }
      var html='<p style="font-size:13px;color:#718096;margin-bottom:16px">'+found.length+' saved article'+(found.length!==1?'s':'')+'</p>';
      html+='<div style="display:flex;flex-direction:column;gap:12px">';
      found.forEach(function(a){
        var cat=a.is_science?'Science':'World News';
        var catColor=a.is_science?'#065f46':'#1e40af';
        var catBg=a.is_science?'#d1fae5':'#dbeafe';
        html+='<div style="background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:16px 18px;font-family:system-ui,sans-serif">'
          +'<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px">'
          +'<div style="flex:1">'
          +'<span style="font-size:11px;font-weight:700;background:'+catBg+';color:'+catColor+';border-radius:12px;padding:2px 10px">'+cat+'</span>'
          +'<a href="/'+a.slug+'" style="display:block;font-size:16px;font-weight:700;color:#1a4d80;text-decoration:none;margin:8px 0 4px;line-height:1.35">'+a.title+'</a>'
          +'<span style="font-size:12px;color:#718096">'+a.date+'</span>'
          +'</div>'
          +'<button onclick="(function(s,el){var K=\'kd_saved\',arr=JSON.parse(localStorage.getItem(K)||\'[]\'),i=arr.indexOf(s);if(i>=0){arr.splice(i,1);}localStorage.setItem(K,JSON.stringify(arr));el.closest(\'[data-slug]\').remove();var c=document.querySelectorAll(\'[data-slug]\').length;var cnt=document.getElementById(\'kd-count\');if(cnt)cnt.textContent=c+\' saved article\'+(c!==1?\'s\':\'\');})(\''+a.slug+'\',this)" data-rm="1" style="background:#fee2e2;color:#991b1b;border:none;border-radius:6px;padding:6px 12px;font-size:12px;cursor:pointer;white-space:nowrap;flex-shrink:0">Remove</button>'
          +'</div>'
          +'</div>';
      });
      html+='</div>';
      el.innerHTML=html;
      var cnt=document.createElement('span');cnt.id='kd-count';
      var cp=el.querySelector('p');if(cp){cp.replaceWith(cnt);cnt.style.cssText='font-size:13px;color:#718096;display:block;margin-bottom:16px';cnt.textContent=found.length+' saved article'+(found.length!==1?'s':'');}
    })
    .catch(function(){el.innerHTML='<p style="color:#718096">Could not load articles. <a href="/news/" style="color:#1a4d80">Go to news</a></p>';});
})();
</script>
</body></html>"""
    upload("saved.html", page, "[scraper] Saved Stories page")
    print(f"  ✓ saved.html — Saved Stories page deployed")


# ── Scraper status page ───────────────────────────────────────────────────────
def generate_status_page(manifest, today, pushed_count):
    articles = manifest.get("articles", [])
    total = len(articles)
    sci   = sum(1 for a in articles if a.get("is_science"))
    world = total - sci
    dates = sorted({a.get("date", "") for a in articles if a.get("date")}, reverse=True)
    last_run = dates[0] if dates else "—"
    biases = [a.get("bias_avg", 0.0) for a in articles]
    avg_bias = (sum(biases) / len(biases)) if biases else 0.0

    source_counts = {}
    for a in articles:
        for icon in a.get("source_icons", "").split():
            source_counts[icon] = source_counts.get(icon, 0) + 1
    top_sources = sorted(source_counts.items(), key=lambda x: -x[1])[:6]
    sources_html = " ".join(
        f'<span style="font-size:24px" title="{icon}: {cnt} articles">{icon}</span>'
        for icon, cnt in top_sources
    )

    # Per-category counts
    _CAT_META = [
        ("science", "&#x1f52c;", "Science", "#d1fae5", "#065f46"),
        ("world", "&#x1f30d;", "World News", "#dbeafe", "#1e40af"),
        ("space", "&#x1f680;", "Space", "#ede9fe", "#5b21b6"),
        ("animals", "&#x1f43e;", "Animals", "#fef3c7", "#92400e"),
        ("history", "&#x1f3db;", "History", "#fce7f3", "#9d174d"),
        ("environment", "&#x1f33f;", "Environment", "#dcfce7", "#166534"),
        ("technology", "&#x1f4bb;", "Technology", "#e0f2fe", "#0369a1"),
    ]
    cat_counts = {"science": sci, "world": world}
    for a in articles:
        for c in (a.get("cats") or []):
            if c not in cat_counts:
                cat_counts[c] = 0
            cat_counts[c] = cat_counts.get(c, 0) + 1
    cat_chips = "".join(
        f'<a href="/news/{key}.html" style="display:inline-flex;align-items:center;gap:5px;'
        f'background:{bg};color:{fg};border-radius:20px;padding:5px 13px;font-size:13px;'
        f'font-weight:700;text-decoration:none;font-family:system-ui,sans-serif">'
        f'{icon} {label} <span style="opacity:.7;font-weight:400">{cat_counts.get(key, 0)}</span></a>'
        for key, icon, label, bg, fg in _CAT_META
        if cat_counts.get(key, 0) > 0
    )

    # Named source breakdown (top 12 by article count using source_name field)
    named_counts = {}
    for a in articles:
        sn = a.get("source_name") or ""
        if sn:
            named_counts[sn] = named_counts.get(sn, 0) + 1
    top_named = sorted(named_counts.items(), key=lambda x: -x[1])[:12]
    source_rows = "".join(
        f'<tr><td style="padding:5px 10px 5px 0;font-size:13px;color:#2d3748">{name}</td>'
        f'<td style="padding:5px 0;font-size:13px;color:#718096;text-align:right">{cnt}</td></tr>'
        for name, cnt in top_named
    )
    source_table = (
        f'<table style="width:100%;border-collapse:collapse;margin-top:10px">'
        f'<thead><tr><th style="text-align:left;font-size:11px;color:#718096;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:.8px;padding-bottom:6px">Source</th>'
        f'<th style="text-align:right;font-size:11px;color:#718096;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:.8px;padding-bottom:6px">Articles</th></tr></thead>'
        f'<tbody>{source_rows}</tbody></table>'
    ) if top_named else ""

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>KiddieDaily — Scraper Status</title>
<meta name="description" content="KiddieDaily automation status — last run, article counts, source breakdown.">
<link rel="canonical" href="https://kiddiedaily.com/status.html">
<link rel="alternate" type="application/rss+xml" title="KiddieDaily RSS" href="/feed.xml">
<style>
body{{margin:0;font-family:system-ui,sans-serif;background:#f0f4f8;color:#2d3748}}
header.kd{{background:#1a4d80;padding:14px 0}}
header.kd .inner{{max-width:980px;margin:0 auto;display:flex;flex-wrap:wrap;align-items:center;gap:18px;padding:0 20px}}
header.kd .logo{{font-weight:700;font-size:22px;color:#fff;font-family:Georgia,serif;text-decoration:none}}
header.kd nav{{display:flex;flex-wrap:wrap;gap:18px;flex:1;justify-content:flex-end}}
header.kd nav a{{color:#fff;font-size:15px}}
main{{max-width:780px;margin:0 auto;padding:32px 24px 64px}}
.stat-card{{background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:20px 24px;margin:12px 0;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.stat-card h3{{margin:0 0 6px;font-size:16px;color:#1a4d80}}
.stat-val{{font-size:32px;font-weight:700;color:#2d3748;margin:4px 0}}
.stat-sub{{font-size:13px;color:#718096}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:16px 0}}
.badge-ok{{display:inline-block;padding:4px 12px;border-radius:20px;background:#d1fae5;color:#065f46;font-size:13px;font-weight:700}}
</style>
</head><body>
<header class="kd"><div class="inner">
  <a class="logo" href="/">📰 KiddieDaily</a>
  <nav>
    <a href="/news/">News</a>
    <a href="/news/science.html">Science</a>
    <a href="/search.html">Search</a>
    <a href="/digest/latest.html">Digest</a>
    <a href="/parent-zone/">Parents</a>
  </nav>
</div></header>
<main id="main">
  <h1 style="font-size:28px;margin:0 0 4px">Automation Status</h1>
  <p style="color:#718096;margin:0 0 24px;font-size:14px">KiddieDaily runs automatically every morning at 6am ET via GitHub Actions.</p>

  <div class="grid">
    <div class="stat-card">
      <h3>Last Run</h3>
      <div class="stat-val">{last_run}</div>
      <div class="stat-sub">Today: +{pushed_count} new article{"s" if pushed_count != 1 else ""}</div>
    </div>
    <div class="stat-card">
      <h3>Total Articles</h3>
      <div class="stat-val">{total}</div>
      <div class="stat-sub">{sci} science &middot; {world} world news</div>
    </div>
    <div class="stat-card">
      <h3>Avg Bias (all sources)</h3>
      <div class="stat-val">{avg_bias:+.2f}</div>
      <div class="stat-sub">Scale: -2 far-left → +2 far-right</div>
    </div>
    <div class="stat-card">
      <h3>Days Covered</h3>
      <div class="stat-val">{len(dates)}</div>
      <div class="stat-sub">Since {dates[-1] if dates else "—"}</div>
    </div>
  </div>

  <div class="stat-card" style="margin-top:20px">
    <h3>Categories</h3>
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:10px">
      {cat_chips}
    </div>
  </div>

  <div class="stat-card" style="margin-top:12px">
    <h3>Pipeline Health</h3>
    <div style="margin:10px 0 6px;display:flex;flex-wrap:wrap;gap:8px">
      <span class="badge-ok">✓ GitHub Actions cron active</span>
      <span class="badge-ok">✓ GitHub Flow (branch → PR → merge)</span>
      <span class="badge-ok">✓ 3-stage CI review</span>
      <span class="badge-ok">✓ {total} articles indexed</span>
      <span class="badge-ok">✓ RSS feed live</span>
    </div>
    <div style="margin-top:12px;font-size:13px;color:#718096">
      Sources monitored: {sources_html}
    </div>
    {source_table}
  </div>

  <div class="stat-card" style="margin-top:16px">
    <h3>Recent Dates</h3>
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:8px">
{"".join(f'      <a href="/digest/{d}.html" style="font-size:13px;padding:4px 10px;background:#dbeafe;color:#1e40af;border-radius:20px;text-decoration:none">{d}</a>' for d in dates[:14])}
    </div>
  </div>

  <p style="margin-top:24px;font-size:13px;color:#718096;text-align:center">
    <a href="https://github.com/Omtatsat101/kiddiedaily" style="color:#1a4d80">View on GitHub</a> &middot;
    <a href="/feed.xml" style="color:#1a4d80">RSS Feed</a> &middot;
    <a href="/sitemap.xml" style="color:#1a4d80">Sitemap</a>
  </p>
</main>
</body></html>"""

    upload("status.html", page, f"[scraper] Status page — {total} articles, last run {today}")
    print(f"  Status page: {total} articles, {len(dates)} days covered")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"\nKiddieDaily Scraper — {today}")
    print("=" * 52)

    # 0. GitHub Flow: create content branch when running in CI (GH_ACTIONS env is set)
    in_ci = bool(os.environ.get("GITHUB_ACTIONS"))
    if in_ci:
        print("\n[0] Setting up GitHub Flow content branch...")
        setup_content_branch(today)
        print(f"    Active branch: {ACTIVE_BRANCH}")

    # 1. Load manifest
    print("\n[1] Loading pushed-article manifest...")
    manifest = load_manifest()
    pushed_slugs = set(manifest.get("pushed_slugs", []))
    pushed_titles = set(t.lower() for t in manifest.get("pushed_titles", []))
    print(f"    {len(pushed_slugs)} articles already pushed")

    # 1b. Self-healing retro-purge: current filters re-applied to whole corpus
    print("\n[1b] Retro-purging filter slip-throughs from corpus...")
    n_retro = retro_purge_filtered(manifest)
    print(f"    {n_retro} slip-through(s) purged" if n_retro else "    Corpus clean — no slip-throughs")

    # 2. Fetch RSS
    print(f"\n[2] Fetching {len(SOURCES)} RSS feeds...")
    all_stories = []
    for src in SOURCES:
        print(f"    {src['icon']} {src['name']}...", end=" ", flush=True)
        stories = fetch_rss(src)
        print(f"{len(stories)} stories")
        all_stories.extend(stories)
        time.sleep(0.3)
    print(f"    Total: {len(all_stories)} stories")

    # 3. Deduplicate against already pushed
    new_stories = [s for s in all_stories if s["title"].lower() not in pushed_titles]
    print(f"\n[3] {len(new_stories)} new stories (not yet pushed)")

    # 4. Group by topic
    print("\n[4] Grouping by topic...")
    groups = group_stories(new_stories)
    print(f"    {len(groups)} unique topics")

    # 5. Generate + push articles
    print(f"\n[5] Generating articles (max {MAX_ARTICLES} per run — up to {MAX_SCI_PER_RUN} science, {MAX_WORLD_PER_RUN} world)...")
    pushed_count = 0
    sci_pushed_run   = 0
    world_pushed_run = 0
    sports_tournament_pushed = {}  # {keyword: count} — cap each live tournament at 1 per run
    source_counts_run = {}  # tracks articles per source this run

    MIN_SCORE = -1  # allow mild heavy-news terms (1 hit) through for world news variety
    skipped_low = 0
    skipped_adult = 0
    skipped_quota = 0

    for group in groups:
        if pushed_count >= MAX_ARTICLES:
            break

        rep = group[0]

        # Skip topics with adult/inappropriate titles (regex, word-boundary safe)
        if _ADULT_TITLE_RE.search(rep["title"]):
            skipped_adult += 1
            print(f"    ⚠ Skipped (adult title): {rep['title'][:60]}")
            continue

        # Hard-reject commercial/shopping titles (score penalty insufficient — science+5 overrides)
        if _COMMERCIAL_TITLE_RE.search(rep["title"]):
            skipped_adult += 1
            print(f"    ⚠ Skipped (commercial): {rep['title'][:60]}")
            continue

        # World news: hard-reject adult-topic stories not appropriate for kids. Applies to ALL
        # articles (even science-source/-tagged ones) so harmful stories mis-tagged as science are
        # still filtered — but exempts clearly-historical framing (archaeology, ancient plague, the
        # Great Famine, "5,000 years ago", etc.) so kids' history/science content survives.
        if _WORLD_NEWS_REJECT_RE.search(rep["title"]) and not _HISTORICAL_RE.search(rep["title"]):
            skipped_adult += 1
            print(f"    ⚠ Skipped (world-reject): {rep['title'][:60]}")
            continue

        # Skip groups that score too low (political noise, single-source political stories)
        if ranking_score(group) < MIN_SCORE:
            skipped_low += 1
            continue

        # Per-run category balance
        is_sci_group = any(s["source_name"] in SCIENCE_SOURCES for s in group)
        if is_sci_group and sci_pushed_run >= MAX_SCI_PER_RUN:
            skipped_quota += 1
            continue
        if not is_sci_group and world_pushed_run >= MAX_WORLD_PER_RUN:
            skipped_quota += 1
            continue

        # Per-tournament cap — prevent any single live event from consuming all world slots
        _LIVE_TOURNAMENTS = ["world cup", "wimbledon", "olympics", "olympic games", "euro 2024", "copa america"]
        _title_lower = rep["title"].lower()
        active_tournament = next((t for t in _LIVE_TOURNAMENTS if t in _title_lower), None) if not is_sci_group else None
        if active_tournament and sports_tournament_pushed.get(active_tournament, 0) >= MAX_SPORTS_TOURNAMENT_PER_RUN:
            skipped_quota += 1
            continue

        # Per-source cap: no single source dominates the run
        primary_source = rep["source_name"]
        if source_counts_run.get(primary_source, 0) >= MAX_PER_SOURCE_PER_RUN:
            skipped_quota += 1
            continue

        # World news: reject high-bias single-source stories (partisan entertainment/opinion)
        if not is_sci_group:
            n = len(group)
            bias_avg = sum(s["source_bias"] for s in group) / n if n else 0.0
            if abs(bias_avg) > MAX_WORLD_NEWS_BIAS and n == 1:
                skipped_low += 1
                continue

        slug = make_slug(rep["title"], today)
        if slug in pushed_slugs:
            continue
        # Title-level dedup: prevents same story appearing on multiple days
        if rep["title"].lower() in pushed_titles:
            continue
        # Fuzzy cross-run dedup: Jaccard similarity against all pushed titles
        # Catches same event covered by different sources on different days (threshold 0.38)
        rep_kw = keywords(rep["title"])
        if rep_kw:
            near_dup = False
            for pt in pushed_titles:
                pt_kw = keywords(pt)
                if pt_kw:
                    shared = len(rep_kw & pt_kw)
                    union = len(rep_kw | pt_kw)
                    if union > 0 and shared / union >= 0.38:
                        near_dup = True
                        break
            if near_dup:
                skipped_low += 1
                continue

        score = score_group(group)
        print(f"\n    Topic: {rep['title'][:60]}...")
        print(f"    Sources: {score['n_sources']} | Bias: {score['bias_avg']:+.2f} | Agreement: {score['agreement_pct']}%")

        # Try API rewrite, fall back to RSS body
        rewritten = None
        if ANTHROPIC_KEY:
            print("    Rewriting with Claude Haiku...")
            rewritten = rewrite_for_kids(rep["title"], rep["description"])

        if rewritten:
            article_title, body_html = body_from_api(rep["title"], rewritten)
            print(f"    → API rewrite: '{article_title[:55]}...'")
        else:
            article_title, body_html = body_from_rss(group)
            print("    → Using RSS content (no API key)")

        bias_html = bias_bar_html(score)
        _page_cats = _article_cats({
            "title": article_title, "slug": slug,
            "is_science": is_sci_group,
            "source_name": group[0].get("source_name", "") if group else "",
        })
        html = build_page(article_title, body_html, bias_html, score, group, slug, today, cats=_page_cats)

        print(f"    Pushing {slug}...")
        result = upload(slug, html, f"[scraper] {article_title[:60]}")

        if result:
            manifest["pushed_slugs"].append(slug)
            manifest["pushed_titles"].append(rep["title"])
            if "articles" not in manifest:
                manifest["articles"] = []
            icons = " ".join(dict.fromkeys(s["source_icon"] for s in group))
            _raw_desc = rep.get("description", "") if rep else ""
            _clean_desc = re.sub(r"<[^>]+>", " ", _raw_desc).strip()[:200]
            manifest["articles"].append({
                "slug": slug,
                "title": rep["title"],
                "display_title": article_title,
                "date": today,
                "n_sources": score["n_sources"],
                "bias_avg": score["bias_avg"],
                "agreement_pct": score["agreement_pct"],
                "is_science": any(s["source_name"] in SCIENCE_SOURCES for s in group),
                "source_name": primary_source,
                "source_icons": icons,
                "description": _clean_desc,
            })
            pushed_count += 1
            source_counts_run[primary_source] = source_counts_run.get(primary_source, 0) + 1
            if is_sci_group:
                sci_pushed_run += 1
            else:
                world_pushed_run += 1
                if active_tournament:
                    sports_tournament_pushed[active_tournament] = sports_tournament_pushed.get(active_tournament, 0) + 1

    if skipped_low:
        print(f"\n    Skipped {skipped_low} low-score topics (political/noise below threshold)")
    if skipped_adult:
        print(f"    Filtered {skipped_adult} adult/inappropriate titles")
    if skipped_quota:
        print(f"    Skipped {skipped_quota} topics (category quota reached)")

    # 6. Save manifest (always if changed: new articles OR migration)
    manifest_dirty = pushed_count > 0 or "articles" in manifest
    if manifest_dirty:
        print(f"\n[6] Saving manifest ({len(manifest.get('articles',[]))} total articles)...")
        save_manifest(manifest)

    # 6b. Always rebuild news index if we have articles
    if manifest.get("articles"):
        print(f"\n[6b] Generating news/index.html hub...")
        generate_news_index_page(manifest)

    # 6c. Always rebuild sitemap (articles + digest dates change daily)
    # Live article slugs only — pushed_slugs retains purged entries whose pages
    # were deleted, and those must not appear in the sitemap as 404s.
    print(f"\n[6c] Updating sitemap.xml...")
    update_sitemap([a.get("slug", "") for a in manifest.get("articles", []) if a.get("slug")], manifest)

    # 6d. Update homepage with latest 3 articles
    print(f"\n[6d] Updating homepage...")
    update_homepage(manifest)

    # 6e. Generate RSS feed
    print(f"\n[6e] Generating RSS feed...")
    generate_rss_feed(manifest)

    # 6f. Update Parent Zone article table
    print(f"\n[6f] Updating Parent Zone...")
    update_parent_zone(manifest)

    # 6g. Generate archive page with client-side search
    print(f"\n[6g] Generating archive page...")
    generate_archive(manifest)

    # 6h. Generate category pages
    print(f"\n[6h] Generating category pages...")
    generate_category_pages(manifest)

    # 6i. Generate articles JSON index (used by related-articles JS on every article page)
    print(f"\n[6i] Generating articles JSON index...")
    generate_articles_json(manifest)

    # 6j. Generate daily digest page
    print(f"\n[6j] Generating daily digest...")
    generate_daily_digest(manifest, today)

    # 6k. Generate today's news page
    print(f"\n[6k] Generating today's news page...")
    generate_today_page(manifest, today)

    # 6k2. Generate weekly digest page
    print(f"\n[6k2] Generating weekly digest...")
    generate_weekly_digest(manifest, today)

    # 6k3. Generate search page
    print(f"\n[6k3] Generating search page...")
    generate_search_page(manifest)

    # 6k3b. Generate saved stories page
    print(f"\n[6k3b] Generating saved stories page...")
    generate_saved_page()

    # 6k4. Generate automation status page
    print(f"\n[6k4] Generating status page...")
    generate_status_page(manifest, today, pushed_count)

    # 6k5. Generate For-Parents briefing page
    print(f"\n[6k5] Generating For-Parents briefing page...")
    generate_for_parents_page(manifest, today)

    # 6k6. Generate Fact Check / media literacy hub
    print(f"\n[6k6] Generating Fact Check / media literacy page...")
    generate_fact_check_page(manifest)

    # 6k7. Generate Games / activities page
    print(f"\n[6k7] Generating Games / activities page...")
    generate_games_page(manifest)

    # 6k7b. Generate Draw the News creativity studio
    print(f"\n[6k7b] Generating Draw the News creativity studio...")
    generate_draw_page(manifest, today)

    # 6k7c. Explore by Wonder — themed discovery collections
    print(f"\n[6k7c] Generating Explore by Wonder hub...")
    generate_explore_by_wonder_page(manifest, today)

    # 6k7d. Maya's Daily Hello — friendly avatar guide
    print(f"\n[6k7d] Generating Maya's Daily Hello...")
    generate_maya_hello(manifest, today)

    # 6k7e. News by the Numbers — data literacy
    print(f"\n[6k7e] Generating News by the Numbers...")
    generate_numbers_page(manifest, today)

    # 6k7f. News Word — daily word-guess game
    print(f"\n[6k7f] Generating News Word game...")
    generate_news_word_page(manifest, today)

    # 6k7g. Time Traveler — history era timeline
    print(f"\n[6k7g] Generating Time Traveler timeline...")
    generate_time_traveler_page(manifest, today)

    # 6k8. Generate static info pages (about, contact, privacy, terms)
    print(f"\n[6k8] Generating static info pages...")
    generate_static_info_pages(manifest, today)

    # 6k8b. Generate subscribe / stay-updated page
    print(f"\n[6k8b] Generating subscribe page...")
    generate_subscribe_page(manifest, today)

    # 6k9. Generate og:image SVGs (used for social sharing previews)
    print(f"\n[6k9] Deploying og:image SVGs for social sharing...")
    _sci_svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
<rect width="1200" height="630" fill="#0f172a"/>
<rect x="0" y="0" width="8" height="630" fill="#34d399"/>
<text x="80" y="90" font-family="system-ui,sans-serif" font-size="28" fill="#34d399" font-weight="700" letter-spacing="2">KIDDIEDAILY</text>
<text x="80" y="135" font-family="system-ui,sans-serif" font-size="18" fill="#94a3b8">News for Families · Science Edition</text>
<text x="80" y="340" font-family="system-ui,sans-serif" font-size="72" fill="#f8fafc">🔬</text>
<text x="200" y="310" font-family="system-ui,sans-serif" font-size="52" fill="#f1f5f9" font-weight="700">Science</text>
<text x="200" y="375" font-family="system-ui,sans-serif" font-size="52" fill="#f1f5f9" font-weight="700">Discovery</text>
<text x="80" y="540" font-family="system-ui,sans-serif" font-size="22" fill="#64748b">Bias-rated · Kid-safe · No ads · kiddiedaily.com</text>
</svg>"""
    _news_svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
<rect width="1200" height="630" fill="#0f172a"/>
<rect x="0" y="0" width="8" height="630" fill="#60a5fa"/>
<text x="80" y="90" font-family="system-ui,sans-serif" font-size="28" fill="#60a5fa" font-weight="700" letter-spacing="2">KIDDIEDAILY</text>
<text x="80" y="135" font-family="system-ui,sans-serif" font-size="18" fill="#94a3b8">News for Families · World News</text>
<text x="80" y="340" font-family="system-ui,sans-serif" font-size="72" fill="#f8fafc">🌍</text>
<text x="200" y="310" font-family="system-ui,sans-serif" font-size="52" fill="#f1f5f9" font-weight="700">World</text>
<text x="200" y="375" font-family="system-ui,sans-serif" font-size="52" fill="#f1f5f9" font-weight="700">News</text>
<text x="80" y="540" font-family="system-ui,sans-serif" font-size="22" fill="#64748b">Bias-rated · Kid-safe · No ads · kiddiedaily.com</text>
</svg>"""
    upload("og-science.svg", _sci_svg, "[scraper] og:image — science articles")
    upload("og-news.svg", _news_svg, "[scraper] og:image — world news articles")
    print("  og:image SVGs deployed: og-science.svg, og-news.svg")

    # 6k10. robots.txt — lets search engines crawl the site and find the sitemap
    print(f"\n[6k10] Deploying robots.txt...")
    _robots = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /data/\n"
        "\n"
        "Sitemap: https://kiddiedaily.com/sitemap.xml\n"
    )
    upload("robots.txt", _robots, "[scraper] robots.txt — allow crawl, point to sitemap")
    print("  robots.txt deployed")

    # 6k11. Web App Manifest — makes KiddieDaily installable as a PWA on mobile/desktop
    print(f"\n[6k11] Deploying web app manifest...")
    _manifest = json.dumps({
        "name": "KiddieDaily",
        "short_name": "KiddieDaily",
        "description": "Daily kid-friendly news with bias indicators — no ads, no agenda",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0f172a",
        "theme_color": "#1a4d80",
        "icons": [
            {
                "src": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%F0%9F%93%B0%3C/text%3E%3C/svg%3E",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any maskable"
            }
        ],
        "categories": ["news", "education"],
        "lang": "en-US"
    }, indent=2)
    upload("manifest.json", _manifest, "[scraper] PWA web app manifest")
    print("  manifest.json deployed")

    # 6k12. Custom 404 page — better UX than GitHub Pages default; redirects to search
    print(f"\n[6k12] Deploying custom 404 page...")
    _404_page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Page Not Found — KiddieDaily</title>
<meta name="description" content="The page you're looking for isn't here. Search KiddieDaily for kid-friendly news.">
<meta name="robots" content="noindex">
{CSS}
</head><body>
{HEADER}
<main id="main" style="max-width:700px;margin:0 auto;padding:48px 24px">
<div style="text-align:center;margin-bottom:36px">
<div style="font-size:64px;margin-bottom:12px">&#128240;</div>
<h1 style="font-size:26px;margin-bottom:6px">Page not found</h1>
<p style="color:#718096;font-family:system-ui,sans-serif;font-size:15px;margin:0 0 20px">
  This story may have moved, or the URL might be misspelled.
</p>
<a href="/search.html" style="display:inline-block;background:#1a4d80;color:#fff;padding:10px 24px;border-radius:8px;text-decoration:none;font-size:15px;font-family:system-ui,sans-serif;font-weight:600;margin-right:10px">
  Search KiddieDaily &rarr;
</a>
<a href="/" style="display:inline-block;background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80;padding:10px 24px;border-radius:8px;font-size:15px;font-family:system-ui,sans-serif;text-decoration:none">
  &larr; Homepage
</a>
</div>
<div id="kd-404-recent" style="margin-top:8px"></div>
<div style="text-align:center;margin-top:28px;padding:16px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:10px;font-family:system-ui,sans-serif">
<p style="margin:0;font-size:14px;color:#075985">&#128241; Browse by topic: <a href="/news/science.html">Science</a> &middot; <a href="/news/space.html">Space</a> &middot; <a href="/news/animals.html">Animals</a> &middot; <a href="/news/history.html">History</a> &middot; <a href="/news/environment.html">Environment</a> &middot; <a href="/news/technology.html">Technology</a></p>
</div>
</main>
{FOOTER}
<script>
fetch('/data/kd-articles.json').then(function(r){{return r.json();}}).then(function(arts){{
  var recent=arts.slice(0,4);
  if(!recent.length)return;
  var el=document.getElementById('kd-404-recent');
  if(!el)return;
  el.innerHTML='<h2 style="font-size:17px;color:#2d3748;font-family:system-ui,sans-serif;margin:0 0 12px">Recent stories you might like</h2>'
    +recent.map(function(a){{
      var bc=a.is_science?'#d1fae5':'#dbeafe';var tc=a.is_science?'#065f46':'#1e40af';var bl=a.is_science?'Science':'World News';
      var ex=a.description?(a.description.length>100?a.description.slice(0,100)+'…':a.description):'';
      return'<div style="margin:8px 0;padding:12px 16px;background:#fff;border:1px solid #e5e7eb;border-radius:8px;font-family:system-ui,sans-serif">'
        +'<span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;background:'+bc+';color:'+tc+';padding:2px 7px;border-radius:20px">'+bl+'</span>'
        +'<a href="/'+a.slug+'" style="display:block;color:#1a4d80;font-weight:600;margin:5px 0 2px;font-size:15px">'+a.title+'</a>'
        +(ex?'<p style="font-size:13px;color:#4a5568;margin:2px 0;line-height:1.4">'+ex+'</p>':'')
        +'<span style="font-size:11px;color:#a0aec0">'+a.date+'</span></div>';
    }}).join('');
}}).catch(function(){{}});
</script>
</body></html>"""
    _404_page = _404_page.replace('{HEADER}', HEADER).replace('{FOOTER}', FOOTER)
    upload("404.html", _404_page, "[scraper] Custom 404 page")
    print("  404.html deployed")

    # 6k13. Homepage WebSite JSON-LD — enables Google sitelinks search box
    print(f"\n[6k13] Injecting WebSite JSON-LD on homepage...")
    _home_resp = gh("GET", f"/repos/{REPO}/contents/index.html?ref={ACTIVE_BRANCH}")
    if isinstance(_home_resp, dict) and not _home_resp.get("_err") and _home_resp.get("content"):
        _home_html = base64.b64decode(_home_resp["content"]).decode("utf-8", errors="replace")
        if 'application/ld+json' not in _home_html:
            _ws_ld = json.dumps({
                "@context": "https://schema.org",
                "@type": "WebSite",
                "name": "KiddieDaily",
                "url": "https://kiddiedaily.com",
                "description": "Daily kid-friendly news — bias-rated, fact-checked, no ads.",
                "potentialAction": {
                    "@type": "SearchAction",
                    "target": {"@type": "EntryPoint",
                               "urlTemplate": "https://kiddiedaily.com/search.html?q={search_term_string}"},
                    "query-input": "required name=search_term_string"
                }
            }, separators=(',', ':'))
            _home_html = _home_html.replace(
                '</head>',
                f'<script type="application/ld+json">{_ws_ld}</script>\n</head>',
                1
            )
            upload("index.html", _home_html, "[scraper] Inject WebSite JSON-LD on homepage for Google sitelinks")
            print("  Homepage WebSite JSON-LD injected")
        else:
            print("  Homepage JSON-LD already present — skipping")
    else:
        print(f"  Could not read index.html: {_home_resp.get('_err') if isinstance(_home_resp, dict) else 'unknown error'}")

    # 6k14. Service worker — stale-while-revalidate cache for kd-articles.json
    print(f"\n[6k14] Deploying service worker (sw.js)...")
    _sw = """\
const CACHE='kd-v1';
self.addEventListener('install',function(e){
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(function(c){return c.add('/data/kd-articles.json');}).catch(function(){}));
});
self.addEventListener('activate',function(e){e.waitUntil(clients.claim());});
self.addEventListener('fetch',function(e){
  if(!e.request.url.includes('kd-articles.json'))return;
  e.respondWith(caches.open(CACHE).then(function(cache){
    return cache.match(e.request).then(function(cached){
      var fresh=fetch(e.request).then(function(r){if(r.ok)cache.put(e.request,r.clone());return r;}).catch(function(){return cached;});
      return cached||fresh;
    });
  }));
});
"""
    upload("sw.js", _sw, "[scraper] Service worker — stale-while-revalidate for kd-articles.json")
    print("  sw.js deployed")

    # 7. Self-deploy: push this script to the kiddiedaily repo so GitHub Actions can find it
    print("\n[7] Self-deploying scraper script to repo...")
    self_src = pathlib.Path(__file__).read_text(encoding="utf-8")
    upload("scrape_and_push.py", self_src, "Deploy/update KiddieDaily scraper script")

    # 8. Push GitHub Actions workflows + governance files (idempotent)
    print("\n[8] Deploying GitHub Actions workflows and governance files...")
    upload(".github/workflows/daily-news.yml", WORKFLOW_YAML,
           "[ci] Update daily news scraper workflow (GitHub Flow)")
    upload(".github/workflows/pr-review.yml", PR_REVIEW_YAML,
           "[ci] Add 3-stage content PR review agent workflow")
    upload(".github/CODEOWNERS", CODEOWNERS_FILE,
           "[ci] Add CODEOWNERS — GitHub best practices")
    upload(".github/PULL_REQUEST_TEMPLATE.md", PR_TEMPLATE_MD,
           "[ci] Add PR template — GitHub best practices")

    # 9. GitHub Flow: open PR and squash-merge content branch → main
    if in_ci and ACTIVE_BRANCH != "main":
        print("\n[9] GitHub Flow: opening PR and merging content branch...")
        create_and_merge_pr(today, pushed_count)

    print(f"\n{'='*52}")
    print(f"DONE. {pushed_count} new article(s) pushed.")
    if pushed_count == 0:
        print("(No new articles — all stories already pushed or no suitable topics found)")

if __name__ == "__main__":
    main()
